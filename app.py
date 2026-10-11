import sys
import cv2
import numpy as np
import wave
import subprocess
import os
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QPushButton, QLineEdit, QLabel, 
                               QProgressBar, QFileDialog, QListWidget, QSpinBox, 
                               QDoubleSpinBox, QGroupBox, QFormLayout)
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QPixmap, QImage, QRect
from PySide6.QtCore import Qt, QBuffer, QIODevice, QThread, Signal
import sounddevice as sd

# ==========================================
# 1. MUSIC SYNTHESIZER
# ==========================================
class Synthesizer:
    NOTE_FREQS = {
        'C': 261.63, 'C#': 277.18, 'D': 293.66, 'D#': 311.13, 'E': 329.63,
        'F': 349.23, 'F#': 369.99, 'G': 392.00, 'G#': 415.30, 'A': 440.00,
        'A#': 466.16, 'B': 493.88
    }

    @staticmethod
    def get_frequency(note):
        if len(note) == 0: return 0
        base = note[0].upper()
        modifier = note[1] if len(note) > 1 and note[1] == '#' else ''
        octave = int(note[-1]) if note[-1].isdigit() else 4
        
        base_freq = Synthesizer.NOTE_FREQS.get(base + modifier, 0)
        if base_freq == 0: return 0
        return base_freq * (2 ** (octave - 4))

    @staticmethod
    def generate_tone(notes, duration=0.5, fs=44100):
        t = np.linspace(0, duration, int(fs * duration), False)
        wave_data = np.zeros_like(t)
        
        for note in notes:
            freq = Synthesizer.get_frequency(note)
            if freq > 0:
                wave_data += np.sin(2 * np.pi * freq * t) * 0.6
                wave_data += np.sin(2 * np.pi * freq * 2 * t) * 0.2
        
        attack = int(0.05 * fs)
        release = int(0.1 * fs)
        envelope = np.ones_like(t)
        envelope[:attack] = np.linspace(0, 1, attack)
        envelope[-release:] = np.linspace(1, 0, release)
        
        wave_data = wave_data * envelope
        max_amp = np.max(np.abs(wave_data))
        if max_amp > 0: wave_data = wave_data / max_amp * 0.8
            
        return wave_data

    @staticmethod
    def play_audio(audio_data, fs=44100):
        sd.play(audio_data, fs)

# ==========================================
# 2. VERTICAL SHEET MUSIC VISUALIZER (9:16)
# ==========================================
class ShortsVisualizer:
    WIDTH = 1080
    HEIGHT = 1920
    
    @staticmethod
    def draw_frame(notes_list, hook_text=""):
        """Draws a 1080x1920 vertical frame for YouTube Shorts."""
        pixmap = QPixmap(ShortsVisualizer.WIDTH, ShortsVisualizer.HEIGHT)
        pixmap.fill(QColor("#101010")) # Dark background typical for shorts
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw Hook Text at the top
        painter.setPen(QColor("#FFFFFF"))
        painter.setFont(QFont("Arial", 40, QFont.Bold))
        painter.drawText(QRect(50, 100, 980, 200), Qt.AlignCenter, hook_text)
        
        # Draw 6 vertical staves
        painter.setFont(QFont("Arial", 24, QFont.Bold))
        painter.setPen(QPen(QColor("#FFFFFF"), 3))
        
        notes_per_stave = 4
        y_start = 450
        
        for row in range(6):
            y_base = y_start + (row * 250)
            
            # Draw Staff Lines
            painter.setPen(QPen(QColor("#888888"), 2))
            for i in range(5):
                painter.drawLine(100, y_base + (i * 25), ShortsVisualizer.WIDTH - 100, y_base + (i * 25))
            
            # Place notes
            x_pos = 200
            painter.setPen(QPen(QColor("#FFD700"), 2)) # Gold notes
            painter.setBrush(QColor("#FFD700"))
            
            for note_item in notes_list[row * notes_per_stave : (row + 1) * notes_per_stave]:
                if not note_item: continue
                
                chord_notes = note_item.split('_')
                y_positions = []
                for n in chord_notes:
                    n = n.strip()
                    base_y = y_base + 100
                    # Map notes to Y positions on the staff
                    if n.startswith('C'): y = base_y
                    elif n.startswith('D'): y = base_y - 12
                    elif n.startswith('E'): y = base_y - 25
                    elif n.startswith('F'): y = base_y - 37
                    elif n.startswith('G'): y = base_y - 50
                    elif n.startswith('A'): y = base_y - 62
                    elif n.startswith('B'): y = base_y - 75
                    else: y = base_y
                    
                    if '#' in n:
                        painter.drawText(x_pos - 40, y + 10, "#")
                    y_positions.append(y)
                
                # Draw note heads and stems
                for y in y_positions:
                    painter.drawEllipse(x_pos, y, 20, 15)
                    painter.drawLine(x_pos + 20, y + 7, x_pos + 20, y - 60)
                
                x_pos += 180
                
        painter.end()
        return pixmap

# ==========================================
# 3. MAIN APPLICATION WINDOW
# ==========================================
class ShortsCreatorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube Shorts Music Creator (3-Min Limit)")
        self.resize(450, 850) # Vertical App Window
        
        self.frames = []
        self.fs = 44100
        
        self.init_ui()
        self.update_duration_est()
        
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # --- Content Input Group ---
        content_group = QGroupBox("Short Content")
        content_layout = QVBoxLayout()
        
        content_layout.addWidget(QLabel("Hook Text (Title at top):"))
        self.hook_input = QLineEdit("Wait for the drop... 🎵")
        content_layout.addWidget(self.hook_input)
        
        content_layout.addWidget(QLabel("Notes (Space=Sequence, _=Chord):"))
        self.seq_input = QLineEdit("C4 D4 E4 F4 G4 A4 B4 C5")
        content_layout.addWidget(self.seq_input)
        
        content_group.setLayout(content_layout)
        layout.addWidget(content_group)
        
        # --- Audio & Action Group ---
        action_layout = QHBoxLayout()
        self.btn_play = QPushButton("▶\nPlay")
        self.btn_play.clicked.connect(self.play_sequence)
        action_layout.addWidget(self.btn_play)
        
        self.btn_add_frame = QPushButton("➕\nAdd Frame")
        self.btn_add_frame.clicked.connect(self.add_visual_frame)
        action_layout.addWidget(self.btn_add_frame)
        layout.addLayout(action_layout)
        
        # --- Frame Queue ---
        self.list_frames = QListWidget()
        self.list_frames.setIconSize(self.list_frames.iconSize().scaled(120, 213, Qt.KeepAspectRatio)) # 9:16 thumbnails
        layout.addWidget(self.list_frames)
        
        # --- Settings ---
        settings_group = QGroupBox("Video Settings")
        settings_layout = QFormLayout()
        
        self.spin_fps = QSpinBox()
        self.spin_fps.setValue(30)
        settings_layout.addRow("FPS:", self.spin_fps)
        
        self.spin_duration = QDoubleSpinBox()
        self.spin_duration.setValue(0.4)
        self.spin_duration.setSingleStep(0.1)
        self.spin_duration.valueChanged.connect(self.update_duration_est)
        settings_layout.addRow("Note Dur (s):", self.spin_duration)
        
        self.lbl_total_dur = QLabel("Total Duration: 0.0s")
        self.lbl_total_dur.setStyleSheet("font-weight: bold; color: #2ecc71;")
        settings_layout.addRow(self.lbl_total_dur)
        
        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)
        
        # --- Export ---
        self.btn_export = QPushButton("Export MP4 (1080x1920)")
        self.btn_export.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold; padding: 15px;")
        self.btn_export.clicked.connect(self.export_mp4)
        layout.addWidget(self.btn_export)
        
        self.progress = QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        
    def update_duration_est(self):
        dur = self.spin_duration.value()
        total_notes = len(self.seq_input.text().split())
        total_est = total_notes * dur * len(self.frames)
        
        # UPDATED: YouTube Shorts limit is now 180 seconds (3 minutes)
        if total_est > 180:
            self.lbl_total_dur.setText(f"Total Duration: {total_est:.1f}s (Over 3 min limit!)")
            self.lbl_total_dur.setStyleSheet("font-weight: bold; color: #e74c3c;")
        else:
            self.lbl_total_dur.setText(f"Total Duration: {total_est:.1f}s (Good for Shorts)")
            self.lbl_total_dur.setStyleSheet("font-weight: bold; color: #2ecc71;")
            
    def play_sequence(self):
        seq_text = self.seq_input.text().strip()
        if not seq_text: return
        
        notes = seq_text.split(' ')
        duration = self.spin_duration.value()
        
        full_audio = []
        for note_item in notes:
            chord_notes = note_item.split('_')
            tone = Synthesizer.generate_tone(chord_notes, duration, self.fs)
            full_audio.append(tone)
            
        audio_data = np.concatenate(full_audio)
        Synthesizer.play_audio(audio_data, self.fs)
        
    def add_visual_frame(self):
        seq_text = self.seq_input.text().strip()
        hook = self.hook_input.text().strip()
        if not seq_text: return
        
        notes = seq_text.split(' ')
        pixmap = ShortsVisualizer.draw_frame(notes, hook)
        
        self.frames.append({"pixmap": pixmap, "notes": notes, "hook": hook})
        
        thumb = pixmap.scaled(120, 213, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.list_frames.addItem(f"Frame {len(self.frames)}")
        self.list_frames.item(len(self.frames)-1).setIcon(thumb)
        
        self.update_duration_est()
        
    def export_mp4(self):
        if not self.frames:
            return
            
        file_path, _ = QFileDialog.getSaveFileName(self, "Save YouTube Short", "short.mp4", "MP4 Files (*.mp4)")
        if not file_path: return
        
        self.btn_export.setEnabled(False)
        self.progress.setValue(0)
        QApplication.processEvents()
        
        fps = self.spin_fps.value()
        duration = self.spin_duration.value()
        frames_per_image = int(fps * duration)
        
        # YouTube Shorts Dimensions (9:16)
        width, height = 1080, 1920
        
        temp_video = "temp_video.mp4"
        temp_audio = "temp_audio.wav"
        
        # 1. Generate Audio
        full_audio = []
        for frame_data in self.frames:
            tone = Synthesizer.generate_tone(frame_data["notes"], duration, self.fs)
            full_audio.append(tone)
        audio_array = np.concatenate(full_audio)
        
        with wave.open(temp_audio, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.fs)
            audio_int16 = (audio_array * 32767).astype(np.int16)
            wf.writeframes(audio_int16.tobytes())
            
        # 2. Generate Video
        # Using H264 codec for YouTube compatibility, fallback to mp4v
        try:
            fourcc = cv2.VideoWriter_fourcc(*'H264')
        except:
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            
        out = cv2.VideoWriter(temp_video, fourcc, fps, (width, height))
        
        total_frames = len(self.frames) * frames_per_image
        count = 0
        
        for frame_data in self.frames:
            pixmap = frame_data["pixmap"]
            
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            pixmap.save(buffer, "PNG")
            buffer.close()
            arr = np.frombuffer(buffer.data(), np.uint8)
            mat = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            mat = cv2.resize(mat, (width, height))
            
            for _ in range(frames_per_image):
                out.write(mat)
                count += 1
                self.progress.setValue(int((count / total_frames) * 50))
                QApplication.processEvents()
                
        out.release()
        
        # 3. Mux Audio and Video using FFmpeg
        try:
            subprocess.run([
                "ffmpeg", "-y",
                "-i", temp_video,
                "-i", temp_audio,
                "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-shortest",
                file_path
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
        except subprocess.CalledProcessError:
            # Fallback if H264 isn't available in local ffmpeg
            subprocess.run([
                "ffmpeg", "-y", "-i", temp_video, "-i", temp_audio,
                "-c:v", "copy", "-c:a", "aac", "-shortest", file_path
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            os.rename(temp_video, file_path)
            os.rename(temp_audio, file_path.replace('.mp4', '.wav'))
        finally:
            if os.path.exists(temp_video): os.remove(temp_video)
            if os.path.exists(temp_audio): os.remove(temp_audio)
            
        self.progress.setValue(100)
        self.btn_export.setEnabled(True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Apply a dark theme globally
    app.setStyleSheet("""
        QWidget { background-color: #1e1e1e; color: #ffffff; }
        QLineEdit, QSpinBox, QDoubleSpinBox { background-color: #2e2e2e; border: 1px solid #444; padding: 5px; border-radius: 3px; }
        QListWidget { background-color: #2e2e2e; border: 1px solid #444; }
        QGroupBox { border: 1px solid #444; border-radius: 5px; margin-top: 1em; font-weight: bold; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
    """)
    window = ShortsCreatorApp()
    window.show()
    sys.exit(app.exec())