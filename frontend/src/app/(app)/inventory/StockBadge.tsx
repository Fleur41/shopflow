import { Badge } from "@/components/ui/Feedback";

export function StockBadge({ status }: { status: string }) {
  if (status === "out") return <Badge tone="warning">Out of stock</Badge>;
  if (status === "low") return <Badge tone="warning">Running low</Badge>;
  return <Badge tone="success">In stock</Badge>;
}
