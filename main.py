import sys
import sqlite3
import cv2
import os
import cvzone
import pickle
import numpy as np
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QGridLayout, QHBoxLayout,
    QLabel, QFileDialog, QDialog, QLineEdit, QMessageBox, QInputDialog, QComboBox, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QPointF
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPen

DB_FILE = "cameras.db"

def errors_func(text):
    msg_box = QMessageBox()
    msg_box.setIcon(QMessageBox.Icon.Critical) 
    msg_box.setWindowTitle("Ошибка") 
    msg_box.setText(text) 
    msg_box.exec()
class PixelEditDialog(QDialog):
    def __init__(self, current_value=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Изменить порог пикселей")
        self.setFixedSize(300, 150)

        layout = QVBoxLayout(self)

        self.label = QLabel("Введите новое значение пикселей:")
        layout.addWidget(self.label)

        self.input_field = QLineEdit()
        if current_value is not None:
            self.input_field.setText(str(current_value))
        layout.addWidget(self.input_field)

        self.save_button = QPushButton("Сохранить")
        self.save_button.clicked.connect(self.accept)
        layout.addWidget(self.save_button)

    def get_value(self):
        return self.input_field.text()
    
class CameraWindow(QWidget):
    def __init__(self, camera_name, video_path):
        super().__init__()
        self.setWindowTitle(f"Камера: {camera_name}")
        self.showMaximized()

        layout = QVBoxLayout(self)
        self.video_label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.video_label)
        self.setLayout(layout)

        self.cap = cv2.VideoCapture(video_path)
        if not self.cap.isOpened():
            errors_func("Ошибка открытия видео")
            
            
        with sqlite3.connect("cameras.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT position, photo FROM cameras WHERE name = ?", (camera_name,))
            row = cursor.fetchone()
            if row:
                self.posList = pickle.loads(row[0]) if row[0] else []
                image_path = row[1]
            else:
                self.posList = []
                image_path = None
        if image_path:
            img_reference = cv2.imread(image_path)
            if img_reference is None:
                errors_func(f"Не удалось загрузить изображение {image_path}")
                return
            self.ref_h, self.ref_w = img_reference.shape[:2]
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.ref_w)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.ref_h)
        else:
            self.ref_w, self.ref_h = None, None

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(30)

        with sqlite3.connect("cameras.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT position FROM cameras WHERE name = ?", (camera_name,))
            row = cursor.fetchone()
            if row and row[0]:
                self.posList = pickle.loads(row[0])
            else:
                self.posList = []
        with sqlite3.connect("cameras.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT pixels FROM cameras WHERE name = ?", (camera_name,))
            result = cursor.fetchone()
            if result:  
                self.count_pixels = result[0]  
            else:
                self.count_pixels = None 

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            dialog = PixelEditDialog(current_value=self.count_pixels, parent=self)
            if dialog.exec():
                new_value_str = dialog.get_value()
                try:
                    new_value = int(new_value_str)
                    self.count_pixels = new_value
                    # Сохраняем в базу
                    with sqlite3.connect("cameras.db") as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE cameras SET pixels = ? WHERE name = ?",
                            (new_value, self.windowTitle().replace("Камера: ", ""))
                        )
                        conn.commit()
                except ValueError:
                    errors_func("Введите корректное числовое значение")
                    
    def checkParkingSpace(self, imgPro, img):
        spaceCounter = 0
        for pos in self.posList:
            pts = np.array(pos, np.int32)
            pts = pts.reshape((-1, 1, 2))

            mask = np.zeros(imgPro.shape, dtype=np.uint8)

            

            cv2.fillPoly(mask, [pts], 255)

            # Накладываем маску на обработанное изображение
            imgCrop = cv2.bitwise_and(imgPro, imgPro, mask=mask)

            # Подсчитываем количество белых пикселей в вырезанной области
            count = cv2.countNonZero(imgCrop)

            # Находим центр полигона для отображения текста
            moments = cv2.moments(pts)
            if moments["m00"] != 0:
                cX = int(moments["m10"] / moments["m00"])
                cY = int(moments["m01"] / moments["m00"])
            else:
                cX, cY = pos[0]  # Если что-то пошло не так, берем первую точку

            # Выводим количество пикселей
            cvzone.putTextRect(img, str(count), (cX-20, cY), scale=1, thickness=2, colorR=(0, 0, 0), offset=0)

            if count < self.count_pixels:
                color = (0, 255, 0)
                thickness = 5
                spaceCounter += 1
            else:
                color = (0, 0, 255)
                thickness = 2

            # Рисуем полигон на исходном изображении
            cv2.polylines(img, [pts], isClosed=True, color=color, thickness=thickness)

        cvzone.putTextRect(img, f"Free: {spaceCounter}/{len(self.posList)}", (50, 50), scale=2, thickness=2, colorR=(0, 0, 0), offset=15)
        
    def update_frame(self):
        success, img = self.cap.read()
        if not success:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            return

        if self.ref_w and self.ref_h:
            img = cv2.resize(img, (self.ref_w, self.ref_h))

        imgGray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        imgBlur = cv2.GaussianBlur(imgGray, (3, 3), 1)
        imgThresh = cv2.adaptiveThreshold(imgBlur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 16)
        imgMedium = cv2.medianBlur(imgThresh, 5)
        kernel = np.ones((3, 3), np.uint8)
        imgDilate = cv2.dilate(imgMedium, kernel, iterations=1)

        self.checkParkingSpace(imgDilate, img)
    
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w, ch = img.shape
        bytes_per_line = ch * w
        q_image = QImage(img.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(q_image).scaled(
            self.video_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.video_label.setPixmap(pixmap)


class CameraMonitorApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Мониторинг парковок")
        self.setGeometry(100, 100, 900, 600)
        self.init_db()
        self.setup_ui()
        self.load_cameras()

    def setup_ui(self):
        main_layout = QHBoxLayout(self)
        button_layout = QVBoxLayout()

        add_btn = QPushButton("--Добавить камеру--")
        add_btn.setFixedWidth(150)
        add_btn.clicked.connect(self.show_add_camera_dialog)
        button_layout.addWidget(add_btn)

        delete_btn = QPushButton("--Удалить камеру--")
        delete_btn.setFixedWidth(150)
        delete_btn.clicked.connect(self.delete_camera_dialog)
        button_layout.addWidget(delete_btn)

        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(10)

        grid_widget = QWidget()
        grid_widget.setLayout(self.grid_layout)

        main_layout.addLayout(button_layout) 
        main_layout.addWidget(grid_widget)   
        
        self.camera_boxes = {}
    def init_db(self):
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cameras (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE,
                    photo TEXT,
                    position BLOB,
                    pixels INTEGER,
                    video TEXT
                )
            """)

    def load_cameras(self):
        with sqlite3.connect(DB_FILE) as conn:
            for camera_id, name, photo, pos_blob, video in conn.execute("SELECT id, name, photo, position, video FROM cameras").fetchall():
                position = pickle.loads(pos_blob)
                self.add_parking_image(camera_id, name, photo, position, video)

    def add_parking_image(self, camera_id, name, photo, position, video):
        if not photo:
            return

        label = QLabel()
        pixmap = QPixmap(photo)

        if pixmap.isNull():
            errors_func("Ошибка загрузки изображения")
            return

        label.setPixmap(pixmap.scaled(300, 200, Qt.AspectRatioMode.KeepAspectRatio))
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFixedSize(300, 200)
        label.setToolTip(name)

        label.mousePressEvent = lambda event, n=name, v=video: self.open_camera(n, v)

        row, col = divmod(len(self.camera_boxes), 3)
        self.grid_layout.addWidget(label, row, col)
        self.camera_boxes[camera_id] = label

    def open_camera(self, name, video_path):
        if video_path:
            self.camera_window = CameraWindow(name, video_path)
            self.camera_window.show()

    
    def show_add_camera_dialog(self):
        dialog = AddCameraDialog(self)
        if dialog.exec():
            name, photo, position, video = dialog.get_camera_data()
            if name and photo and position and video:
                self.add_camera_to_db(name, photo, position, video)


    def update_camera_display(self):
        # Очистить текущий grid
        for i in reversed(range(self.grid_layout.count())):
            widget = self.grid_layout.itemAt(i).widget()
            if widget is not None:
                widget.setParent(None)

        self.camera_boxes.clear()

        # Получить камеры из базы данных
        with sqlite3.connect(DB_FILE) as conn:
            cameras = conn.execute("SELECT id, name, photo, video FROM cameras").fetchall()

        for idx, (camera_id, name, photo, video) in enumerate(cameras):
            if not photo or not os.path.exists(photo):
                continue  # пропустить, если нет фото

            pixmap = QPixmap(photo)
            if pixmap.isNull():
                continue  # если изображение не удалось загрузить

            label = QLabel()
            label.setPixmap(pixmap.scaled(300, 200, Qt.AspectRatioMode.KeepAspectRatio))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setFixedSize(300, 200)
            label.setToolTip(name)

            # Установим обработчик клика
            label.mousePressEvent = lambda event, n=name, v=video: self.open_camera(n, v)

            row, col = divmod(len(self.camera_boxes), 3)
            self.grid_layout.addWidget(label, row, col)
            self.camera_boxes[camera_id] = label

    def delete_camera_dialog(self):
        dialog = DeleteCameraDialog(self)
        if dialog.exec():
            self.update_camera_display()


    def add_camera_to_db(self, name, photo, position, video):
        try:
            with sqlite3.connect(DB_FILE) as conn:
                pos_blob = pickle.dumps(position) 
                cursor = conn.execute(
                    "INSERT INTO cameras (name, photo, position, video, pixels) VALUES (?, ?, ?, ?, ?)",
                    (name, photo, pos_blob, video, 0)
                )
                conn.commit()
                camera_id = cursor.lastrowid
            self.add_parking_image(camera_id, name, photo, position, video)
        except sqlite3.IntegrityError:
            errors_func("Камера с таким названием существует")

class AddCameraDialog(QDialog):
    """Диалог для добавления камеры."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Добавить камеру")

        self.position = []

        layout = QVBoxLayout(self)

        self.input_name = QLineEdit(self, placeholderText="Название парковки")
        layout.addWidget(self.input_name)

        self.btn_select_photo = QPushButton("Выбрать фото")
        self.btn_select_photo.clicked.connect(self.select_photo)
        layout.addWidget(self.btn_select_photo)

        self.photo_path_label = QLabel("Файл не выбран")
        layout.addWidget(self.photo_path_label)

        self.btn_select_positions = QPushButton("Выбрать позиции на парковке")
        self.btn_select_positions.clicked.connect(self.show_add_position_dialog)
        self.btn_select_positions.setEnabled(False)
        layout.addWidget(self.btn_select_positions)

        self.btn_select_video = QPushButton("Выбрать видео")
        self.btn_select_video.clicked.connect(self.select_video)
        layout.addWidget(self.btn_select_video)

        self.video_path_label = QLabel("Файл не выбран")
        layout.addWidget(self.video_path_label)

        self.add_button = QPushButton("Добавить")
        self.add_button.clicked.connect(self.add_camera)
        layout.addWidget(self.add_button)

        self.setLayout(layout)

        self.photo_path = ""
        self.video_path = ""

    def select_photo(self):
        """Выбирает фото."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Выбрать изображение", "", "Изображения (*.png *.jpg *.jpeg)")
        if file_path:
            self.photo_path = file_path
            self.photo_path_label.setText(file_path.split("/")[-1])
            self.btn_select_positions.setEnabled(True)
        else:
            self.photo_path_label.setText("Файл не выбран")
            self.btn_select_positions.setEnabled(False)

    def show_add_position_dialog(self):
        dialog = AddPositionDialog(self, self.photo_path)
        if dialog.exec():
            self.position = dialog.positions 
        else:
            self.position = []
        
    def select_video(self):
        """Выбирает видео."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Выбрать видео", "", "Видео (*.mp4 *.avi *.mov)")
        if file_path:
            self.video_path = file_path
            self.video_path_label.setText(file_path.split("/")[-1])

    def add_camera(self):
        """Сохраняет камеру и закрывает диалог."""
        if self.input_name.text().strip() and self.photo_path and self.position and self.video_path:
            self.accept()  # Закрываем окно только если все данные есть

    def get_camera_data(self):
        """Возвращает введенные данные."""
        return self.input_name.text().strip(), self.photo_path, self.position, self.video_path

    
class AddPositionDialog(QDialog):
    def __init__(self, parent=None, photo_path=None):
        super().__init__(parent)
        self.setWindowTitle("Добавление парковочных позиций")
        self.setFixedSize(800, 600)

        self.photo_path = photo_path
        self.positions = []
        self.current_polygon = []
        self.selection_mode = None
        self.rect_width = 0
        self.rect_height = 0

        self.saved_length = 0
        self.saved_width = 0

        self.image_label = QLabel()
        self.pixmap = QPixmap(self.photo_path)
        self.image_label.setPixmap(self.pixmap)
        self.image_label.setScaledContents(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self.image_label)

        buttons_layout = QHBoxLayout()
        self.btn_save = QPushButton("Сохранить")
        self.btn_save.clicked.connect(self.save_positions)

        self.btn_add_form = QPushButton("Добавить форму")
        self.btn_add_form.clicked.connect(self.add_form)

        self.btn_cancel = QPushButton("Выйти")
        self.btn_cancel.clicked.connect(self.close)

        buttons_layout.addWidget(self.btn_save)
        buttons_layout.addWidget(self.btn_cancel)
        buttons_layout.addWidget(self.btn_add_form)

        buttons_widget = QWidget()
        buttons_widget.setLayout(buttons_layout)
        layout.addWidget(buttons_widget)

        # Включаем отслеживание событий мыши
        self.image_label.installEventFilter(self)

    def add_form(self):
        dialog = ShapeDialog(self, saved_length=self.saved_length, saved_width=self.saved_width)
        if dialog.exec():
            length, width = dialog.get_dimensions()
            self.rect_width = width
            self.rect_height = length

            self.saved_length = length
            self.saved_width = width

            if length == 0 and width == 0:
                self.selection_mode = "polygon"
                print("Режим: полигональное выделение")
            else:
                self.selection_mode = "rectangle"
                print(f"Режим: прямоугольник {width}x{length}")
            
    def eventFilter(self, source, event):
        if source == self.image_label and event.type() == event.Type.MouseButtonPress:
            label_rect = self.image_label.rect()
            img_width = self.pixmap.width()
            img_height = self.pixmap.height()

            pos = event.position()
            x, y = int(pos.x()), int(pos.y())

            scale_x = img_width / label_rect.width()
            scale_y = img_height / label_rect.height()
            img_x = int(x * scale_x)
            img_y = int(y * scale_y)

            if event.button() == Qt.MouseButton.LeftButton:
                if self.saved_length == 0 and self.saved_width == 0:
                    self.current_polygon.append((img_x, img_y))
                    if len(self.current_polygon) == 4:
                        self.positions.append(self.current_polygon.copy())
                        self.current_polygon.clear()
                elif self.selection_mode == "rectangle":
                    # Строим прямоугольник от центра
                    w, h = self.rect_width // 2, self.rect_height // 2
                    rect = [
                        (img_x - w, img_y - h),
                        (img_x + w, img_y - h),
                        (img_x + w, img_y + h),
                        (img_x - w, img_y + h)
                    ]
                    self.positions.append(rect)
            elif event.button() == Qt.MouseButton.RightButton:
                if self.current_polygon:
                    self.current_polygon.pop()
                elif self.positions:
                    self.positions.pop()

            self.update_image()
        return super().eventFilter(source, event)

    def update_image(self):
        temp_pixmap = QPixmap(self.pixmap)
        painter = QPainter(temp_pixmap)

        pen_polygon = QPen(Qt.GlobalColor.green, 2)
        pen_point = QPen(Qt.GlobalColor.red, 5)

        painter.setPen(pen_polygon)
        for polygon in self.positions:
            if len(polygon) >= 2:
                points = [QPointF(x, y) for x, y in polygon]
                painter.drawPolygon(*points)

        painter.setPen(pen_point)
        for x, y in self.current_polygon:
            painter.drawPoint(x, y)

        painter.end()
        self.image_label.setPixmap(temp_pixmap)

    def save_positions(self):
        self.accept()      
class ShapeDialog(QDialog):
    def __init__(self, parent=None, saved_length=0, saved_width=0):
        super().__init__(parent)
        self.setWindowTitle("Параметры формы")
        self.setFixedSize(250, 150)

        layout = QVBoxLayout(self)
        self.length_input = QLineEdit(str(saved_length))
        self.width_input = QLineEdit(str(saved_width))

        layout.addWidget(QLabel("Длина:"))
        layout.addWidget(self.length_input)
        layout.addWidget(QLabel("Ширина:"))
        layout.addWidget(self.width_input)

        btn_ok = QPushButton("Применить")
        btn_ok.clicked.connect(self.accept)
        layout.addWidget(btn_ok)

    def get_dimensions(self):
        try:
            length = int(self.length_input.text())
            width = int(self.width_input.text())
        except ValueError:
            length = width = 0
        return length, width

class DeleteCameraDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Удалить камеру")
        self.setFixedSize(300, 150)

        layout = QVBoxLayout(self)

        with sqlite3.connect(DB_FILE) as conn:
            cameras = conn.execute("SELECT name FROM cameras").fetchall()

        self.camera_names = [c[0] for c in cameras]

        if not self.camera_names:
            QMessageBox.warning(self, "Ошибка", "Нет доступных камер для удаления.")
            self.close()
            return

        self.combo = QComboBox()
        self.combo.addItems(self.camera_names)
        layout.addWidget(QLabel("Выберите камеру для удаления:"))
        layout.addWidget(self.combo)

        btn_layout = QHBoxLayout()
        self.delete_btn = QPushButton("Удалить")
        self.delete_btn.clicked.connect(self.delete_camera)
        btn_layout.addWidget(self.delete_btn)

        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        layout.addLayout(btn_layout)

    def delete_camera(self):
        selected_name = self.combo.currentText()
        if selected_name:
            confirm = QMessageBox.question(
                self,
                "Подтверждение",
                f"Вы уверены, что хотите удалить камеру '{selected_name}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if confirm == QMessageBox.StandardButton.Yes:
                with sqlite3.connect(DB_FILE) as conn:
                    conn.execute("DELETE FROM cameras WHERE name = ?", (selected_name,))
                self.accept()  # Закрыть диалог с успехом


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CameraMonitorApp()
    window.show()
    sys.exit(app.exec())
