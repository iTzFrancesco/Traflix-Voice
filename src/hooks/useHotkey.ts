import { useState, useCallback, useEffect, useRef } from "react";

const CONTROL_MODIFIERS = new Set(["Control", "ControlLeft", "ControlRight"]);

function formatKey(key: string, code: string): string {
  const map: Record<string, string> = {
    Control: "Control",
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

function formatModifier(e: KeyboardEvent): string | null {
  switch (e.key) {
    case "Control":
      if (e.code === "ControlLeft") return "ControlLeft";
      if (e.code === "ControlRight") return "ControlRight";
      return "Control";
    case "Alt":
      return "Alt";
    case "Shift":
      return "Shift";
    case "Meta":
      return "Super";
    default:
      return null;
  }
}

function hasModifier(keys: string[], modifier: Set<string>): boolean {
  return keys.some((key) => modifier.has(key));
}

function modifiersFromEvent(e: KeyboardEvent, recordedModifiers: string[]): string[] {
  const keys = [...recordedModifiers];
  if (e.ctrlKey && !hasModifier(keys, CONTROL_MODIFIERS)) keys.push("Control");
  if (e.altKey && !keys.includes("Alt")) keys.push("Alt");
  if (e.shiftKey && !keys.includes("Shift")) keys.push("Shift");
  if (e.metaKey && !keys.includes("Super")) keys.push("Super");
  return keys;
}

export function useHotkey() {
  const [isRecording, setIsRecording] = useState(false);
  const [recordedKeys, setRecordedKeys] = useState("");
  const recordingRef = useRef(false);
  const recordedModifiersRef = useRef<string[]>([]);
  const pressedModifiersRef = useRef(new Set<string>());
  const hasNonModifierRef = useRef(false);

  // Sync ref with state
  useEffect(() => {
    recordingRef.current = isRecording;
  }, [isRecording]);

  const startRecording = useCallback(() => {
    recordedModifiersRef.current = [];
    pressedModifiersRef.current.clear();
    hasNonModifierRef.current = false;
    setIsRecording(true);
    setRecordedKeys("");
  }, []);

  const stopRecording = useCallback(() => {
    recordedModifiersRef.current = [];
    pressedModifiersRef.current.clear();
    hasNonModifierRef.current = false;
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
        recordedModifiersRef.current = [];
        pressedModifiersRef.current.clear();
        hasNonModifierRef.current = false;
        setRecordedKeys("AltGraph");
        setIsRecording(false);
        return;
      }

      const modifier = formatModifier(e);
      if (modifier) {
        if (e.repeat) return;
        if (!recordedModifiersRef.current.includes(modifier)) {
          recordedModifiersRef.current.push(modifier);
        }
        pressedModifiersRef.current.add(modifier);
        setRecordedKeys(`${recordedModifiersRef.current.join("+")}+...`);
      } else {
        const keys = modifiersFromEvent(e, recordedModifiersRef.current);
        keys.push(formatKey(e.key, e.code));
        hasNonModifierRef.current = true;
        setRecordedKeys(keys.join("+"));
        setIsRecording(false);
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      if (!recordingRef.current) return;

      const modifier = formatModifier(e);
      if (!modifier) return;

      pressedModifiersRef.current.delete(modifier);
      if (
        hasNonModifierRef.current ||
        pressedModifiersRef.current.size > 0 ||
        recordedModifiersRef.current.length === 0
      ) {
        return;
      }

      setRecordedKeys(recordedModifiersRef.current.join("+"));
      setIsRecording(false);
    };

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
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
