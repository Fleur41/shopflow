import { Suspense } from "react";

import { SaleDetail } from "./SaleDetail";

export default function SalePage() {
  return (
    <Suspense>
      <SaleDetail />
    </Suspense>
  );
}
