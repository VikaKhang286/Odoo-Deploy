// /** @odoo-module **/

// import { registry } from "@web/core/registry";

// registry.category("services").add("dac_erp.chatter_autopen_service", {
//   start() {
//     const clickNoteIfNeeded = () => {
//       // Chỉ chạy trên form
//       const form = document.querySelector(".o_form_view");
//       if (!form) return false;

//       // Nếu ô nhập ghi chú đã mở thì thôi
//       if (document.querySelector(".o-mail-Composer")) return true;

//       // Tìm & click nút "Ghi chú"
//       const btn = form.querySelector(".o-mail-Chatter-logNote");
//       if (btn && !btn.classList.contains("active") && !btn.disabled) {
//         btn.dispatchEvent(
//           new MouseEvent("click", { bubbles: true, cancelable: true })
//         );
//       }
//       return true;
//     };

//     // Thử một lần ngay khi service nạp
//     setTimeout(clickNoteIfNeeded, 0);

//     // Theo dõi thay đổi DOM (đổi bản ghi, reload chatter…)
//     const obs = new MutationObserver(() => {
//       if (!document.querySelector(".o-mail-Composer")) {
//         clickNoteIfNeeded();
//       }
//     });
//     obs.observe(document.body, { childList: true, subtree: true });

//     return {
//       stop() {
//         obs.disconnect();
//       },
//     };
//   },
// });
