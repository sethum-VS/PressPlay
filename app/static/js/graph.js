(function () {
  const dataEl = document.getElementById("graph-data");
  const container = document.getElementById("graph-container");
  const svgEl = document.getElementById("graph-svg");
  if (!dataEl || !container || !svgEl || typeof d3 === "undefined") return;

  let data;
  try {
    data = JSON.parse(dataEl.textContent);
  } catch (e) {
    console.warn("Invalid graph JSON", e);
    return;
  }

  const nodes = (data.nodes || []).map((n) => ({ ...n }));
  const links = (data.edges || data.links || []).map((e) => ({
    source: e.source,
    target: e.target,
    label: e.label || e.relation || "",
  }));

  if (!nodes.length) {
    svgEl.innerHTML = "";
    const empty = document.createElementNS("http://www.w3.org/2000/svg", "text");
    empty.setAttribute("x", "50%");
    empty.setAttribute("y", "50%");
    empty.setAttribute("text-anchor", "middle");
    empty.setAttribute("fill", "#807d72");
    empty.setAttribute("font-size", "13");
    empty.textContent = "No entities extracted";
    svgEl.appendChild(empty);
    return;
  }

  const width = container.clientWidth || 400;
  const height = container.clientHeight || 256;

  const svg = d3
    .select(svgEl)
    .attr("viewBox", [0, 0, width, height])
    .attr("width", width)
    .attr("height", height);

  svg.selectAll("*").remove();

  const color = (group) => {
    const g = (group || "entity").toLowerCase();
    if (g === "org" || g === "organization") return "#a83300";
    if (g === "vehicle" || g === "hardware") return "#005baf";
    if (g === "location") return "#1f8a65";
    if (g === "product" || g === "topic") return "#c08532";
    return "#605e56";
  };

  const simulation = d3
    .forceSimulation(nodes)
    .force(
      "link",
      d3
        .forceLink(links)
        .id((d) => d.id)
        .distance(72)
    )
    .force("charge", d3.forceManyBody().strength(-220))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collision", d3.forceCollide().radius(22));

  const link = svg
    .append("g")
    .attr("stroke", "#cfcdc4")
    .attr("stroke-opacity", 0.85)
    .selectAll("line")
    .data(links)
    .join("line")
    .attr("stroke-width", 1.5);

  const linkLabel = svg
    .append("g")
    .selectAll("text")
    .data(links.filter((l) => l.label))
    .join("text")
    .attr("font-size", "9px")
    .attr("font-family", "Inter, sans-serif")
    .attr("fill", "#a09c92")
    .attr("text-anchor", "middle")
    .text((d) => d.label);

  const node = svg.append("g").selectAll("g").data(nodes).join("g").call(
    d3
      .drag()
      .on("start", (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on("drag", (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on("end", (event, d) => {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      })
  );

  node
    .append("circle")
    .attr("r", 10)
    .attr("fill", (d) => color(d.group))
    .attr("stroke", "#fff")
    .attr("stroke-width", 1.5);

  node
    .append("text")
    .text((d) => d.label)
    .attr("x", 14)
    .attr("y", 4)
    .attr("font-size", "11px")
    .attr("font-family", "Inter, sans-serif")
    .attr("fill", "#26251e");

  simulation.on("tick", () => {
    link
      .attr("x1", (d) => d.source.x)
      .attr("y1", (d) => d.source.y)
      .attr("x2", (d) => d.target.x)
      .attr("y2", (d) => d.target.y);

    linkLabel
      .attr("x", (d) => (d.source.x + d.target.x) / 2)
      .attr("y", (d) => (d.source.y + d.target.y) / 2);

    node.attr("transform", (d) => `translate(${d.x},${d.y})`);
  });
})();
