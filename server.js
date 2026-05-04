const express = require("express");
const cors = require("cors");
const qrcode = require("qrcode-terminal");
const { Client, LocalAuth } = require("whatsapp-web.js");

const app = express();
app.use(cors());
app.use(express.json());

const client = new Client({
    authStrategy: new LocalAuth()
});

client.on("qr", (qr) => {
    console.log("📱 Scan this QR code:");
    qrcode.generate(qr, { small: true });
});

client.on("ready", () => {
    console.log("✅ WhatsApp is ready!");
});

client.initialize();

app.post("/send", async (req, res) => {
    try {
        const { phone, message } = req.body;

        const chatId = phone + "@c.us";

        await client.sendMessage(chatId, message);

        res.json({ success: true });
    } catch (err) {
        console.log(err);
        res.status(500).json({ success: false });
    }
});

app.listen(5001, () => {
    console.log("🚀 Server running on port 5001");
});