// Dàn bố cục sơ đồ bằng ELK (layered): đọc graph JSON từ stdin, in kết quả ra stdout.
// Toạ độ trả về là toạ độ tuyệt đối (ROOT) cho cả khối lẫn đường nối.
import ELK from "elkjs/lib/elk.bundled.js";

const chunks = [];
for await (const c of process.stdin) chunks.push(c);
const graph = JSON.parse(Buffer.concat(chunks).toString("utf8"));

const elk = new ELK();
graph.layoutOptions = {
  "elk.algorithm": "layered",
  "elk.direction": graph.direction || "DOWN",
  "elk.hierarchyHandling": "INCLUDE_CHILDREN",
  "elk.edgeRouting": "ORTHOGONAL",
  "elk.layered.spacing.nodeNodeBetweenLayers": "70",
  "elk.spacing.nodeNode": "44",
  "elk.spacing.edgeNode": "26",
  "elk.spacing.edgeEdge": "18",
  "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
  "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
  // BALANCED: nút có nhiều nhánh vào/ra nằm giữa các nhánh (mặc định hay dồn hết về bên trái)
  "elk.layered.nodePlacement.bk.fixedAlignment": "BALANCED",
  "elk.edgeLabels.inline": "false",
  "org.eclipse.elk.json.shapeCoords": "ROOT",
  "org.eclipse.elk.json.edgeCoords": "ROOT",
  ...(graph.layoutOptions || {}),
};
delete graph.direction;

try {
  const out = await elk.layout(graph);
  process.stdout.write(JSON.stringify(out));
} catch (e) {
  process.stderr.write(String(e && e.stack || e));
  process.exit(1);
}
