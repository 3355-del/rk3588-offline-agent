"""Offline speech recognizers, used only by the cancellable speech worker."""
from pathlib import Path
import wave
import array
import sys


def model_files(backend):
    if backend == 'vosk':
        return ('am/final.mdl',)
    if backend == 'sensevoice':
        return ('model.int8.onnx', 'tokens.txt')
    raise ValueError('unsupported asr_backend')


def recognize(path, model, backend='vosk', threads=2):
    model_files(backend)
    model = Path(model).resolve()
    with wave.open(str(path), 'rb') as wav:
        pcm = wav.readframes(wav.getnframes())
    samples = array.array('h', pcm)
    if sys.byteorder != 'little':samples.byteswap()
    # Reject digital silence/DC and near-quantization noise. This is not a VAD
    # and must not be advertised as reliably distinguishing speech from noise.
    if not samples or max(samples)-min(samples) < 16:
        return ''
    if backend == 'sensevoice':
        import numpy as np
        import sherpa_onnx
        recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model/'model.int8.onnx'), tokens=str(model/'tokens.txt'),
            num_threads=threads, language='zh', use_itn=True, provider='cpu')
        samples = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768.0
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, samples)
        recognizer.decode_stream(stream)
        return stream.result.text.strip()
    model_files(backend)  # Reject unknown backends instead of silently falling back.
    import json, os
    from vosk import Model, KaldiRecognizer, SetLogLevel
    SetLogLevel(-1)
    # This function runs in a dedicated worker; work around Vosk's Windows paths.
    os.chdir(model.parent)
    with wave.open(str(path), 'rb') as wav:
        recognizer = KaldiRecognizer(Model(model.name), 16000)
        parts = []
        while data := wav.readframes(4000):
            if recognizer.AcceptWaveform(data):
                parts.append(json.loads(recognizer.Result()).get('text', ''))
        parts.append(json.loads(recognizer.FinalResult()).get('text', ''))
    return ' '.join(part for part in parts if part).strip()
