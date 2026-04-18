// ── EXPORT FUNCTIONALITY ──

function initializeExportFunctionality(transcriptionBox, showToast) {
  const exportBtn = document.querySelector("#export-btn");
  const exportDropdown = document.querySelector("#export-dropdown");
  const exportOptions = document.querySelectorAll(".export-option");

  // Toggle dropdown visibility
  if (exportBtn && exportDropdown) {
    exportBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const isExpanded = exportDropdown.classList.toggle("show");
      exportBtn.setAttribute("aria-expanded", isExpanded);
    });

    // Close dropdown when clicking outside
    document.addEventListener("click", (e) => {
      if (!exportBtn.contains(e.target) && !exportDropdown.contains(e.target)) {
        exportDropdown.classList.remove("show");
        exportBtn.setAttribute("aria-expanded", "false");
      }
    });
  }

  // Handle export option selection
  exportOptions.forEach(option => {
    option.addEventListener("click", async (e) => {
      e.stopPropagation();
      const format = option.getAttribute("data-format");
      exportDropdown.classList.remove("show");
      exportBtn.setAttribute("aria-expanded", "false");
      await exportTranscription(format, transcriptionBox, showToast);
    });
  });
}

async function exportTranscription(format, transcriptionBox, showToast) {
  if (!transcriptionBox || !transcriptionBox.value.trim()) {
    showToast("Nessuna trascrizione da esportare!", "info");
    return;
  }

  try {
    const content = transcriptionBox.value;
    let exportContent;
    let defaultFilename;

    if (format === "txt") {
      exportContent = content;
      defaultFilename = "trascrizione.txt";
    } else if (format === "srt") {
      exportContent = convertToSRT(content);
      defaultFilename = "trascrizione.srt";
    } else {
      return;
    }

    // Create a download using browser API
    const blob = new Blob([exportContent], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = defaultFilename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showToast(`File ${defaultFilename} esportato con successo`, "success");
    console.log(`[export] File ${defaultFilename} esportato con successo`);
  } catch (err) {
    console.error("[export] Errore durante l'esportazione:", err);
    showToast("Errore durante l'esportazione del file", "error");
  }
}

function convertToSRT(text) {
  // Parse the transcription text and convert to SRT format
  // Assumes format: [HH:MM] text\n
  const lines = text.split("\n").filter(line => line.trim());
  let srtContent = "";
  let index = 1;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;

    // Try to extract timestamp [HH:MM]
    const timestampMatch = line.match(/^\[(\d{1,2}):(\d{2})\]\s*(.+)$/);

    if (timestampMatch) {
      const hours = timestampMatch[1].padStart(2, '0');
      const minutes = timestampMatch[2];
      const textContent = timestampMatch[3];

      // Calculate approximate duration (3 seconds per entry)
      const startTime = `${hours}:${minutes}:00,000`;

      // Calculate end time (add 3 seconds)
      let endHours = parseInt(hours);
      let endMinutes = parseInt(minutes);
      let endSeconds = 3;

      if (endSeconds >= 60) {
        endMinutes += Math.floor(endSeconds / 60);
        endSeconds = endSeconds % 60;
      }
      if (endMinutes >= 60) {
        endHours += Math.floor(endMinutes / 60);
        endMinutes = endMinutes % 60;
      }

      const endTime = `${String(endHours).padStart(2, '0')}:${String(endMinutes).padStart(2, '0')}:${String(endSeconds).padStart(2, '0')},000`;

      srtContent += `${index}\n`;
      srtContent += `${startTime} --> ${endTime}\n`;
      srtContent += `${textContent}\n\n`;
      index++;
    } else {
      // No timestamp found, create generic timestamps
      const startSeconds = (index - 1) * 3;
      const endSeconds = index * 3;

      const startHours = Math.floor(startSeconds / 3600);
      const startMinutes = Math.floor((startSeconds % 3600) / 60);
      const startSecs = startSeconds % 60;

      const endHours = Math.floor(endSeconds / 3600);
      const endMinutes = Math.floor((endSeconds % 3600) / 60);
      const endSecs = endSeconds % 60;

      const startTime = `${String(startHours).padStart(2, '0')}:${String(startMinutes).padStart(2, '0')}:${String(startSecs).padStart(2, '0')},000`;
      const endTime = `${String(endHours).padStart(2, '0')}:${String(endMinutes).padStart(2, '0')}:${String(endSecs).padStart(2, '0')},000`;

      srtContent += `${index}\n`;
      srtContent += `${startTime} --> ${endTime}\n`;
      srtContent += `${line}\n\n`;
      index++;
    }
  }

  return srtContent;
}
