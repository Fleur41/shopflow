import { Suspense } from "react";

import { ReceiptView } from "./ReceiptView";

export default function ReceiptPage() {
  return (
    <Suspense>
      <ReceiptView />
    </Suspense>
  );
}
