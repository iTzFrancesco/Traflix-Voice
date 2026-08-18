export function convertToSRT(text: string): string {
  const lines = text.split("\n").filter((line) => line.trim());
  let srtContent = "";
  let index = 1;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;

    const timestampMatch = line.match(/^\[(\d{1,2}):(\d{2})\]\s*(.+)$/);

    if (timestampMatch) {
      // Formato atteso: [mm:ss] Testo
      const minutes = parseInt(timestampMatch[1]);
      const seconds = parseInt(timestampMatch[2]);
      const textContent = timestampMatch[3];
      const startTime = `00:${String(minutes).padStart(2, "0")}:${String(
        seconds
      ).padStart(2, "0")},000`;
      const endSec = minutes * 60 + seconds + 3;
      const endH = Math.floor(endSec / 3600);
      const endM = Math.floor((endSec % 3600) / 60);
      const endS = endSec % 60;

      const endTime = `${String(endH).padStart(2, "0")}:${String(
        endM
      ).padStart(2, "0")}:${String(endS).padStart(2, "0")},000`;

      srtContent += `${index}\n`;
      srtContent += `${startTime} --> ${endTime}\n`;
      srtContent += `${textContent}\n\n`;
      index++;
    } else {
      const startSeconds = (index - 1) * 3;
      const endSeconds = index * 3;
      const startH = Math.floor(startSeconds / 3600);
      const startM = Math.floor((startSeconds % 3600) / 60);
      const startS = startSeconds % 60;
      const endH = Math.floor(endSeconds / 3600);
      const endM = Math.floor((endSeconds % 3600) / 60);
      const endS = endSeconds % 60;

      srtContent += `${index}\n`;
      srtContent += `${String(startH).padStart(2, "0")}:${String(
        startM
      ).padStart(2, "0")}:${String(startS).padStart(2, "0")},000 --> ${String(
        endH
      ).padStart(2, "0")}:${String(endM).padStart(2, "0")}:${String(
        endS
      ).padStart(2, "0")},000\n`;
      srtContent += `${line}\n\n`;
      index++;
    }
  }
  return srtContent;
}
