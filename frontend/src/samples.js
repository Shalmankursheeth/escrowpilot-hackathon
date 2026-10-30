// Sample documents that match a deal, so the demo can be run without typing paperwork.
export function sampleDoc(deal, kind, { wrongQty = false } = {}) {
  const qty = deal.quantity || 1000;
  const goods = deal.goods || "goods";
  const n = Math.floor(100000 + Math.random() * 900000);
  const q = wrongQty ? Math.round(qty * 0.8) : qty;
  const titles = {
    order_confirmation: ["ORDER CONFIRMATION", "OC", deal.seller, deal.buyer],
    bill_of_lading: ["BILL OF LADING", "BL", deal.seller, deal.buyer],
    commercial_invoice: ["COMMERCIAL INVOICE", "CI", deal.seller, deal.buyer],
    packing_list: ["PACKING LIST", "PL", deal.seller, deal.buyer],
    delivery_receipt: ["DELIVERY RECEIPT", "DR", deal.seller, deal.buyer],
    return_receipt: ["RETURN RECEIPT", "RR", deal.buyer, deal.seller],
  };
  const [title, prefix, from, to] = titles[kind];
  return `${title}\nDocument Number: ${prefix}-${n}\nShipper: ${from}\nConsignee: ${to}\nGoods: ${q} units of ${goods}\nQuantity: ${q}\n`;
}
