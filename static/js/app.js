const textarea = document.getElementById("news-text");
const urlInput = document.getElementById("news-url");
const charCount = document.getElementById("char-count");
const analyzeBtn = document.getElementById("analyze-btn");
const btnText = analyzeBtn.querySelector(".btn-text");
const spinner = analyzeBtn.querySelector(".spinner");
const resultsSection = document.getElementById("results");
const errorBanner = document.getElementById("error-banner");
const sourceUrlBadge = document.getElementById("source-url-badge");

const dropZone = document.getElementById("drop-zone");
const imageInput = document.getElementById("image-input");
const uploadPlaceholder = document.getElementById("upload-placeholder");
const imagePreview = document.getElementById("image-preview");
const previewImg = document.getElementById("preview-img");
const removeImageBtn = document.getElementById("remove-image");

let selectedFile = null;

// Character counter
textarea.addEventListener("input", () => {
  const len = textarea.value.length;
  charCount.textContent = `${len} / 8000`;
});

// Click to open file dialog
dropZone.addEventListener("click", (e) => {
  if (e.target === removeImageBtn) return;
  imageInput.click();
});

// File selected
imageInput.addEventListener("change", () => {
  if (imageInput.files && imageInput.files[0]) {
    handleFile(imageInput.files[0]);
  }
});

// Drag & drop
dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("dragover");
});

dropZone.addEventListener("dragleave", () => {
  dropZone.classList.remove("dragover");
});

dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("dragover");
  if (e.dataTransfer.files && e.dataTransfer.files[0]) {
    handleFile(e.dataTransfer.files[0]);
  }
});

removeImageBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  clearImage();
});

function handleFile(file) {
  const allowed = ["image/jpeg", "image/png", "image/webp", "image/gif"];
  if (!allowed.includes(file.type)) {
    showError("Unsupported file type. Please use JPG, PNG, WEBP or GIF.");
    return;
  }
  if (file.size > 8 * 1024 * 1024) {
    showError("Image is too large (max 8 MB).");
    return;
  }

  selectedFile = file;
  const reader = new FileReader();
  reader.onload = (e) => {
    previewImg.src = e.target.result;
    uploadPlaceholder.classList.add("hidden");
    imagePreview.classList.remove("hidden");
  };
  reader.readAsDataURL(file);
  hideError();
}

function clearImage() {
  selectedFile = null;
  imageInput.value = "";
  previewImg.src = "";
  imagePreview.classList.add("hidden");
  uploadPlaceholder.classList.remove("hidden");
}

// Analyze button
analyzeBtn.addEventListener("click", async () => {
  const text = textarea.value.trim();
  const url = urlInput.value.trim();

  if (!text && !selectedFile && !url) {
    showError("Please provide a URL, some text, or an image to analyze.");
    return;
  }

  // Basic client-side URL check
  if (url && !/^https?:\/\//i.test(url)) {
    showError("URL must start with http:// or https://");
    return;
  }

  setLoading(true);
  hideError();
  resultsSection.classList.add("hidden");
  sourceUrlBadge.classList.add("hidden");

  try {
    const formData = new FormData();
    if (text) formData.append("text", text);
    if (url) formData.append("url", url);
    if (selectedFile) formData.append("image", selectedFile);

    const res = await fetch("/analyze", {
      method: "POST",
      body: formData,
    });

    const data = await res.json();

    if (!res.ok) {
      showError(data.error || "Something went wrong.");
      return;
    }

    // Show soft warning if fetch had issues but we still got results
    if (data.fetch_warning) {
      showError("Note: " + data.fetch_warning);
    }

    renderResults(data);
  } catch (err) {
    showError("Network error. Is the server running?");
  } finally {
    setLoading(false);
  }
});

function setLoading(isLoading) {
  analyzeBtn.disabled = isLoading;
  spinner.classList.toggle("hidden", !isLoading);
  btnText.textContent = isLoading ? "Analyzing..." : "Analyze with AI";
}

function showError(msg) {
  errorBanner.textContent = msg;
  errorBanner.classList.remove("hidden");
}

function hideError() {
  errorBanner.classList.add("hidden");
}

function renderResults(data) {
  const { combined, groq, gemini, source_url } = data;

  // Source URL badge
  if (source_url) {
    sourceUrlBadge.innerHTML = `Analyzed from: <a href="${source_url}" target="_blank" rel="noopener">${source_url}</a>`;
    sourceUrlBadge.classList.remove("hidden");
  } else {
    sourceUrlBadge.classList.add("hidden");
  }

  // Combined
  const finalVerdict = document.getElementById("final-verdict");
  finalVerdict.textContent = combined.final_verdict;
  finalVerdict.className = `verdict-badge ${combined.final_verdict}`;

  const conf = combined.final_confidence || 0;
  document.getElementById("confidence-fill").style.width = `${conf}%`;
  document.getElementById("confidence-value").textContent = `${conf}%`;
  document.getElementById("combined-explanation").textContent =
    combined.explanation || "";

  // Groq
  renderModel("groq", groq);

  // Gemini
  renderModel("gemini", gemini);

  // Show extracted text if present
  const extractedSection = document.getElementById("extracted-text-section");
  const extractedEl = document.getElementById("gemini-extracted");
  if (gemini && gemini.extracted_text && gemini.extracted_text.trim()) {
    extractedEl.textContent = gemini.extracted_text;
    extractedSection.style.display = "block";
  } else {
    extractedSection.style.display = "none";
  }

  resultsSection.classList.remove("hidden");
  resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderModel(prefix, result) {
  const errorEl = document.getElementById(`${prefix}-error`);
  const verdictEl = document.getElementById(`${prefix}-verdict`);
  const summaryEl = document.getElementById(`${prefix}-summary`);

  if (result.error) {
    errorEl.textContent = result.error;
    errorEl.classList.remove("hidden");
    verdictEl.textContent = "ERROR";
    verdictEl.className = "verdict-badge small ERROR";
    summaryEl.textContent = "";
    clearList(`${prefix}-reasons`);
    clearList(`${prefix}-redflags`);
    clearList(`${prefix}-checks`);
    return;
  }

  errorEl.classList.add("hidden");

  const verdict = (result.verdict || "UNCERTAIN").toUpperCase();
  verdictEl.textContent = verdict;
  verdictEl.className = `verdict-badge small ${verdict}`;

  summaryEl.textContent = result.summary || "No summary provided.";

  fillList(`${prefix}-reasons`, result.reasons || []);
  fillList(`${prefix}-redflags`, result.red_flags || []);
  fillList(`${prefix}-checks`, result.suggested_checks || []);
}

function fillList(id, items) {
  const ul = document.getElementById(id);
  ul.innerHTML = "";
  if (!items.length) {
    const li = document.createElement("li");
    li.textContent = "None noted";
    li.style.color = "var(--text-muted)";
    ul.appendChild(li);
    return;
  }
  items.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    ul.appendChild(li);
  });
}

function clearList(id) {
  document.getElementById(id).innerHTML = "";
}
