export async function registerSpike({ root, caseId, frame, record, loadAssetModule }) {
  if (!root || typeof root.replaceChildren !== "function") {
    throw new TypeError("S10 requires the shared renderer root.");
  }
  if (typeof loadAssetModule !== "function") {
    throw new TypeError("S10 requires the shared asset-module loader.");
  }

  const { mountColourPage } = await loadAssetModule("pages/colour/colour.js");

  return mountColourPage(root, {
    caseId: caseId,
    frame: frame,
    record: record
  });
}

