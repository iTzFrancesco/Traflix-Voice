# Traflix Voice context

This glossary defines the language shared by desktop and Android dictation
flows. It separates the user's voice session, the cloud result, and the text
destination so platform-specific adapters do not redefine the same concepts.

## Dictation

**Dictation session**:
A user-initiated interval in which spoken audio is captured for one transcript.
_Avoid_: recording, transcription job

**Transcript**:
The text produced from one dictation session, including its language and
duration metadata.
_Avoid_: result text, pasted text

**Cloud transcription**:
A transcription performed by a remote provider after the user has consented to
send the session audio off the device.
_Avoid_: online mode, Groq call

## Destination

**Active editor**:
The text field and cursor/selection chosen by the user when a dictation starts.
_Avoid_: focused app, target window

**Text sink**:
The platform-specific destination that commits a transcript to the active
editor or exposes it for an explicit user recovery action.
_Avoid_: paste handler, output box

**Pending transcript**:
A completed transcript that cannot be committed safely because the active
editor changed or the insertion operation failed.
_Avoid_: failed paste, lost result

## User data

**Dictation history**:
The user-visible collection of completed transcripts retained by the product
according to its privacy settings.
_Avoid_: cloud history, transcript cache

**Temporary audio**:
Audio retained only long enough to complete or explicitly retry a dictation.
_Avoid_: recording archive, microphone cache
