const functions = require("firebase-functions");
const { GoogleAuth } = require("google-auth-library");
const fetch = (...args) => import("node-fetch").then(({ default: f }) => f(...args));

const CLOUD_RUN_URL = "https://aeo-grader-api-juemzurita-ew.a.run.app";
const auth = new GoogleAuth();

// Gen 1 proxy: /api/** → Cloud Run (Firebase Hosting auto-invokes Gen 1 without extra auth)
exports.api = functions
  .region("europe-west1")
  .runWith({ timeoutSeconds: 120, memory: "256MB" })
  .https.onRequest(async (req, res) => {
    // CORS headers
    res.set("Access-Control-Allow-Origin", "*");
    res.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    res.set("Access-Control-Allow-Headers", "Content-Type");
    if (req.method === "OPTIONS") {
      res.status(204).send("");
      return;
    }

    // Build target URL: strip /api prefix
    const path = req.path.replace(/^\/api/, "") || "/chat";
    const targetUrl = `${CLOUD_RUN_URL}${path}`;

    // Get OIDC token for Cloud Run auth
    try {
      const client = await auth.getIdTokenClient(CLOUD_RUN_URL);
      const headers = await client.getRequestHeaders(targetUrl);

      const upstream = await fetch(targetUrl, {
        method: req.method,
        headers: {
          "Content-Type": "application/json",
          ...headers,
        },
        body: req.method !== "GET" ? JSON.stringify(req.body) : undefined,
      });

      const data = await upstream.json();
      return res.status(upstream.status).json(data);
    } catch (err) {
      console.error("Upstream error:", err);
      return res.status(502).json({ error: "Bad gateway", detail: err.message });
    }
  });
