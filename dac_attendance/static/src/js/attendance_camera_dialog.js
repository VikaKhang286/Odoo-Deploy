/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class DacAttendanceCameraDialog extends Component {
    static template = "dac_attendance.CameraDialog";
    static components = { Dialog };
    static props = {
        close: { type: Function },
        isCheckOut: { type: Boolean, optional: true },
        employeeName: { type: String, optional: true },
        onPhotoTaken: { type: Function },
    };

    setup() {
        this.videoRef = useRef("cameraVideo");
        this.canvasRef = useRef("cameraCanvas");
        this.state = useState({
            cameraReady: false,
            photoTaken: false,
            photoDataUrl: null,
            gpsStatus: "loading",
            gpsLat: null,
            gpsLng: null,
            errorMessage: null,
            submitting: false,
        });
        this.stream = null;
        this.photoBase64 = null;

        onMounted(() => this._initCamera());
        onWillUnmount(() => this._stopCamera());
    }

    async _initCamera() {
        try {
            // Request camera - facingMode 'user' for selfie, no gallery allowed
            this.stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: "user",
                    width: { ideal: 640 },
                    height: { ideal: 480 },
                },
                audio: false,
            });
            const video = this.videoRef.el;
            if (video) {
                video.srcObject = this.stream;
                video.play();
                this.state.cameraReady = true;
            }
        } catch (e) {
            console.error("Camera error:", e);
            this.state.errorMessage = "Không thể mở camera. Vui lòng cho phép truy cập camera trong trình duyệt.";
        }

        // Get GPS position
        this._getGPS();
    }

    _getGPS() {
        if (!navigator.geolocation) {
            this.state.gpsStatus = "unavailable";
            return;
        }
        navigator.geolocation.getCurrentPosition(
            (pos) => {
                this.state.gpsLat = pos.coords.latitude;
                this.state.gpsLng = pos.coords.longitude;
                this.state.gpsStatus = "ready";
            },
            (err) => {
                console.warn("GPS error:", err.message);
                this.state.gpsStatus = "error";
            },
            { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 }
        );
    }

    _stopCamera() {
        if (this.stream) {
            this.stream.getTracks().forEach((t) => t.stop());
            this.stream = null;
        }
    }

    capturePhoto() {
        const video = this.videoRef.el;
        const canvas = this.canvasRef.el;
        if (!video || !canvas) return;

        const ctx = canvas.getContext("2d");
        canvas.width = video.videoWidth || 640;
        canvas.height = video.videoHeight || 480;

        // Draw video frame
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

        // Draw metadata overlay
        const now = new Date();
        const timestamp = now.toLocaleString("vi-VN", {
            year: "numeric", month: "2-digit", day: "2-digit",
            hour: "2-digit", minute: "2-digit", second: "2-digit",
        });

        // Semi-transparent overlay bar at bottom
        const barHeight = 60;
        ctx.fillStyle = "rgba(0, 0, 0, 0.7)";
        ctx.fillRect(0, canvas.height - barHeight, canvas.width, barHeight);

        ctx.fillStyle = "#ffffff";
        ctx.font = "bold 16px Arial, sans-serif";

        // Line 1: Timestamp + Employee name
        const actionText = this.props.isCheckOut ? "CHECK-OUT" : "CHECK-IN";
        const employeeName = this.props.employeeName || "";
        ctx.fillText(`${actionText} | ${employeeName} | ${timestamp}`, 10, canvas.height - 35);

        // Line 2: GPS coordinates
        let gpsText = "GPS: Không có";
        if (this.state.gpsLat && this.state.gpsLng) {
            gpsText = `GPS: ${this.state.gpsLat.toFixed(6)}, ${this.state.gpsLng.toFixed(6)}`;
        }
        ctx.font = "14px Arial, sans-serif";
        ctx.fillText(gpsText, 10, canvas.height - 12);

        // Get base64
        const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
        this.photoBase64 = dataUrl.split(",")[1];
        this.state.photoDataUrl = dataUrl;
        this.state.photoTaken = true;

        // Stop camera preview
        this._stopCamera();
    }

    retakePhoto() {
        this.state.photoTaken = false;
        this.state.photoDataUrl = null;
        this.photoBase64 = null;
        this._initCamera();
    }

    async confirmPhoto() {
        if (!this.photoBase64 || this.state.submitting) return;
        this.state.submitting = true;

        const metadata = {
            timestamp: new Date().toISOString(),
            latitude: this.state.gpsLat,
            longitude: this.state.gpsLng,
        };

        try {
            await this.props.onPhotoTaken(this.photoBase64, metadata);
            this.props.close();
        } catch (e) {
            this.state.errorMessage = `Lỗi: ${e.message}`;
            this.state.submitting = false;
        }
    }

    get dialogTitle() {
        return this.props.isCheckOut ? "Chụp ảnh Check-out" : "Chụp ảnh Check-in";
    }
}
