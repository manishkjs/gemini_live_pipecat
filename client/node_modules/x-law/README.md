<p align="center">
  <h1 align="center">x-law</h1>
  <p align="center">
    <a href="https://www.npmjs.com/package/x-law">
      <img src="https://img.shields.io/npm/v/x-law.svg" alt="NPM" />
    </a>
    <a href="https://nitodeco.github.io/xlaw/">
      <img src="https://img.shields.io/badge/docs-online-blue.svg" alt="Docs" />
    </a>
    <a href="https://github.com/nitodeco/xlaw/blob/main/LICENSE">
      <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License" />
    </a>
  </p>
  <h3 align="center">
    A-Law, μ-Law and common audio utilites for JavaScript/TypeScript
  </h3>
</p>

This package started as a rewrite of the [alawmulaw](https://github.com/rochars/alawmulaw) library in TypeScript for a modernized build process and updated dependencies. It adds additional utilities and features for processing audio data, such as loudness calculation, more flexible encoding/decoding, and more.

Primarily intended for use in a backend environment.

## Install

```
npm install x-law
```

## Usage

CommonJS:

```javascript
const { alaw, mulaw, utils } = require("x-law");
```

ESM:

```javascript
import { alaw, mulaw, utils } from "x-law";
```

## Examples

### Basic Usage

```typescript
import { alaw, mulaw } from "x-law";

// Convert between PCM and μ-Law/A-Law
const pcmSamples = new Int16Array([
  /* 16-bit PCM samples */
]);

// Encode to μ-Law
const mulawSamples = mulaw.encode(pcmSamples); // Returns Uint8Array
// Decode back to PCM
const decodedPcm = mulaw.decode(mulawSamples); // Returns Int16Array

// Encode to A-Law
const alawSamples = alaw.encode(pcmSamples); // Returns Uint8Array
// Decode back to PCM
const decodedAlawPcm = alaw.decode(alawSamples); // Returns Int16Array

// Working with Buffer objects
const pcmBuffer = Buffer.from(pcmSamples.buffer);
const encodedMulaw = mulaw.encodeBuffer(pcmBuffer);
const decodedBuffer = mulaw.decodeBuffer(encodedMulaw);
```

### Single Sample Processing

```typescript
import { alaw, mulaw } from "x-law";

// Single sample conversion
const pcmSample = 16384; // 16-bit PCM sample
const mulawSample = mulaw.encodeSample(pcmSample);
const decodedSample = mulaw.decodeSample(mulawSample);

const alawSample = alaw.encodeSample(pcmSample);
const decodedAlawSample = alaw.decodeSample(alawSample);
```

### Audio Processing Utilities

```typescript
import { utils } from "x-law";

// Calculate RMS loudness in decibels
const buffer = Buffer.from(/* PCM audio data */);
const loudness = utils.calculateLoudness(buffer, 16); // For 16-bit PCM
console.log(`RMS Loudness: ${loudness} dB`);

// Resample audio (e.g., from 48kHz to 16kHz)
const samples = [
  /* PCM samples */
];
const resampled = utils.resample(samples, 48000, 16000, 16); // 16-bit depth

// Create a WAV header for audio data
const dataSize = pcmSamples.byteLength;
const wavHeader = utils.createWavHeader(
  dataSize, // Size of audio data in bytes
  44100, // Sample rate (Hz)
  1, // Channels (1 = mono, 2 = stereo)
  16 // Bit depth (8, 16, 24, or 32)
);

// Write WAV file
const wavFile = Buffer.concat([wavHeader, Buffer.from(pcmSamples.buffer)]);
fs.writeFileSync("output.wav", wavFile);
```

You can find the full documentation [here](https://nitodeco.github.io/xlaw/).

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for more details.

### LICENSE

This project is licensed under the MIT license. See [LICENSE](LICENSE) for more details.
