import { useState, useCallback, useEffect, useRef } from "react";

function formatKey(key: string, code: string): string {
  const map: Record<string, string> = {
    Control: "CommandOrControl",
    Alt: "Alt",
    Shift: "Shift",
    " ": "Space",
    Meta: "Super",
  };
  // Use the physical key code for layout-independent shortcuts. On an
  // Italian keyboard, for example, e.key may be "ù" while e.code is "KeyU".
  if (/^Key[A-Z]$/.test(code)) return code.slice(3);
  if (/^Digit[0-9]$/.test(code)) return code.slice(5);
  if (/^F(?:[1-9]|1[0-2])$/.test(code)) return code;

  return map[key] || key.charAt(0).toUpperCase() + key.slice(1);
}

export function useHotkey() {
  const [isRecording, setIsRecording] = useState(false);
  const [recordedKeys, setRecordedKeys] = useState("");
  const recordingRef = useRef(false);

  // Sync ref with state
  useEffect(() => {
    recordingRef.current = isRecording;
  }, [isRecording]);

  const startRecording = useCallback(() => {
    setIsRecording(true);
    setRecordedKeys("");
  }, []);

  const stopRecording = useCallback(() => {
    setIsRecording(false);
  }, []);

  // Keyboard handler during recording
  useEffect(() => {
    if (!isRecording) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (!recordingRef.current) return;
      e.preventDefault();

      // AltGr is reported as Ctrl+Alt by Windows/browser layouts, but it is
      // also a distinct physical key. Keep it as a standalone shortcut.
      if (e.key === "AltGraph" || e.code === "AltRight") {
        setRecordedKeys("AltGraph");
        setIsRecording(false);
        return;
      }

      const keys: string[] = [];
      if (e.ctrlKey) keys.push("CommandOrControl");
      if (e.altKey) keys.push("Alt");
      if (e.shiftKey) keys.push("Shift");
      if (e.metaKey) keys.push("Super");

      const isModifier = ["Control", "Alt", "Shift", "Meta"].includes(e.key);

      if (!isModifier) {
        keys.push(formatKey(e.key, e.code));
        setRecordedKeys(keys.join("+"));
        setIsRecording(false);
      } else {
        setRecordedKeys(keys.join("+") + "+...");
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isRecording]);

  // Mouse button handler during recording
  useEffect(() => {
    if (!isRecording) return;

    const handleMouseDown = (e: MouseEvent) => {
      if (!recordingRef.current) return;

      let mouseKey: string | null = null;
      if (e.button === 3) mouseKey = "XBUTTON1";
      else if (e.button === 4) mouseKey = "XBUTTON2";
      else return;

      e.preventDefault();

      const keys: string[] = [];
      if (e.ctrlKey) keys.push("CommandOrControl");
      if (e.altKey) keys.push("Alt");
      if (e.shiftKey) keys.push("Shift");
      if (e.metaKey) keys.push("Super");
      keys.push(mouseKey);

      setRecordedKeys(keys.join("+"));
      setIsRecording(false);
    };

    window.addEventListener("mousedown", handleMouseDown);
    return () => window.removeEventListener("mousedown", handleMouseDown);
  }, [isRecording]);

  return {
    isRecording,
    recordedKeys,
    startRecording,
    stopRecording,
  };
}
