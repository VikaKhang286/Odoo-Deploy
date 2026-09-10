/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

class InvoiceUploadDialog extends Component {
    static template = "sale_ai_invoice_reader.InvoiceUploadDialog";
    static components = { Dialog };
    static props = {
        orderId: { type: Number, optional: true },
        close: Function,
    };

    setup() {
        this.state = useState({
            fileData: null,
            filename: "",
            isDragging: false,
            isLoading: false,
            errorMsg: "",
            isImage: false,   // Fix #1: track whether the file is an image
        });
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.fileInputRef = useRef("fileInput");
        this.cameraInputRef = useRef("cameraInput");

        const onPaste = (e) => this._onPaste(e);
        onMounted(() => document.addEventListener("paste", onPaste));
        onWillUnmount(() => document.removeEventListener("paste", onPaste));
    }

    _onPaste(event) {
        const items = event.clipboardData?.items;
        if (!items) return;
        for (const item of items) {
            if (item.type.startsWith("image/")) {
                const file = item.getAsFile();
                if (file) {
                    this._processFile(file);
                    break;
                }
            }
        }
    }

    _processFile(file) {
        // Fix #1: detect image type for preview thumbnail
        this.state.isImage = file.type.startsWith("image/");
        const reader = new FileReader();
        reader.onload = (e) => {
            this.state.fileData = e.target.result.split(",")[1];
            this.state.filename = file.name || "invoice.png";
            this.state.errorMsg = "";
        };
        reader.readAsDataURL(file);
    }

    onDragOver(event) {
        event.preventDefault();
        this.state.isDragging = true;
    }

    onDragLeave() {
        this.state.isDragging = false;
    }

    onDrop(event) {
        event.preventDefault();
        this.state.isDragging = false;
        const file = event.dataTransfer?.files?.[0];
        if (file) this._processFile(file);
    }

    onFileChange(event) {
        const file = event.target.files?.[0];
        if (file) this._processFile(file);
    }

    onClickZone() {
        this.fileInputRef.el?.click();
    }

    onClickCamera() {
        this.cameraInputRef.el?.click();
    }

    async onReadInvoice() {
        if (!this.state.fileData) {
            this.state.errorMsg = "Vui lòng tải lên hoặc paste ảnh/PDF trước!";
            return;
        }
        this.state.isLoading = true;
        this.state.errorMsg = "";
        try {
            const action = await this.orm.call(
                "sale.order",
                "action_read_invoice_ai_from_data",
                [],
                {
                    file_data: this.state.fileData,
                    filename: this.state.filename,
                    order_id: this.props.orderId || false,
                }
            );
            if (!action) {
                this.state.errorMsg = "AI không trả về dữ liệu hóa đơn. Vui lòng thử lại.";
                return;
            }
            // Mở wizard preview TRƯỚC khi đóng dialog upload — nếu đóng trước,
            // doAction(target='new') có thể bị nuốt im lặng do component đã unmount.
            await this.actionService.doAction(action);
            this.props.close();
        } catch (error) {
            this.state.errorMsg =
                error?.data?.message || error.message || "Có lỗi xảy ra khi đọc hóa đơn.";
        } finally {
            this.state.isLoading = false;
        }
    }
}

// Client action handler: opens the upload dialog without navigating away
registry.category("actions").add("sale_ai_invoice_reader.open_upload_dialog", (env, action) => {
    env.services.dialog.add(InvoiceUploadDialog, {
        orderId: action.params?.order_id || undefined,
    });
});
