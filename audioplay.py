import speech_recognition as sr
import os
import subprocess
import time
import webbrowser
import winsound
import ctypes
import re
import keyboard
import threading
from datetime import datetime, timedelta

# ============================================
# ГРОМКОСТЬ ЧЕРЕЗ WINDOWS CORE AUDIO
# без эмуляции клавиш
# ============================================
try:
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
    import comtypes
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    PYCAW_AVAILABLE = True
    PYCAW_ERROR = ""
except Exception as e:
    PYCAW_AVAILABLE = False
    PYCAW_ERROR = str(e)


game_path = r"C:\Games\Tanks_Blitz\tanksblitz.exe"
game_process_name = "tanksblitz.exe"

youtube_url = "https://www.youtube.com"
qwen_url = "https://chat.qwen.ai"
music_url = "https://music.youtube.com"

lm_studio_path = r"C:\Users\user\AppData\Local\Programs\LM Studio\LM studio.exe"
lm_studio_process_name = "lm studio.exe"
edge_process_name = "msedge.exe"

# Несколько вариантов пути на случай, если папка/файл называются немного по-разному
obhod_paths = [
    r"C:\Users\user\Desktop\обход\general (ALT).bat",
    r"C:\Users\user\Desktop\обход название файла\general (ALT).bat",
    r"C:\Users\user\Desktop\обход название файла general (ALT).bat",
    r"C:\Users\user\Desktop\general (ALT).bat",
]

r = sr.Recognizer()
r.energy_threshold = 300
r.dynamic_energy_threshold = False

last_youtube_open_time = 0
last_qwen_open_time = 0
last_music_open_time = 0

YOUTUBE_COOLDOWN = 30
QWEN_COOLDOWN = 30
MUSIC_COOLDOWN = 30

voice_enabled = True

manual_exit_event = threading.Event()
command_lock = threading.Lock()


def _ensure_com():
    try:
        comtypes.CoInitialize()
    except Exception:
        pass


def _try_activate_volume_interface(obj):
    """
    Пытается получить IAudioEndpointVolume через Activate/activate.
    """
    if obj is None:
        return None

    for method_name in ("Activate", "activate"):
        if hasattr(obj, method_name):
            try:
                interface = getattr(obj, method_name)(
                    IAudioEndpointVolume._iid_,
                    CLSCTX_ALL,
                    None
                )
                return cast(interface, POINTER(IAudioEndpointVolume))
            except Exception:
                pass

    return None


def _collect_audio_candidates(obj, depth=0):
    """
    Собирает возможные варианты аудио-объектов,
    потому что разные версии pycaw могут возвращать разные обёртки.
    """
    candidates = [obj]

    if obj is None or depth > 3:
        return candidates

    for attr in ("device", "_device", "mm_device", "imm_device", "endpoint", "com_device"):
        if hasattr(obj, attr):
            try:
                inner = getattr(obj, attr)
                candidates.extend(_collect_audio_candidates(inner, depth + 1))
            except Exception:
                pass

    return candidates


def get_audio_endpoint():
    """
    Получает системное аудио-устройство.
    Совместимо с разными версиями pycaw.
    """
    if not PYCAW_AVAILABLE:
        return None

    try:
        try:
            _ensure_com()
        except Exception:
            pass

        speakers = AudioUtilities.GetSpeakers()

        # Собираем сам объект и возможные внутренние устройства
        candidates = _collect_audio_candidates(speakers)

        # Если есть методы получения громкости — пробуем их
        for candidate in list(candidates):
            for method in ("GetVolume", "GetEndpointVolume", "GetVolumeObject", "GetAudioEndpointVolume"):
                if hasattr(candidate, method):
                    try:
                        candidates.append(getattr(candidate, method)())
                    except Exception:
                        pass

        # Ищем готовый объект громкости или делаем Activate
        for candidate in candidates:
            if candidate is None:
                continue

            if hasattr(candidate, "SetMasterVolumeLevelScalar") and hasattr(candidate, "GetMasterVolumeLevelScalar"):
                return candidate

            endpoint = _try_activate_volume_interface(candidate)
            if endpoint is not None:
                return endpoint

        # Запасной вариант: ищем нужные интерфейсы в атрибутах
        for name in dir(speakers):
            if name.startswith("__"):
                continue

            try:
                val = getattr(speakers, name)
            except Exception:
                continue

            if hasattr(val, "SetMasterVolumeLevelScalar") and hasattr(val, "GetMasterVolumeLevelScalar"):
                return val

            endpoint = _try_activate_volume_interface(val)
            if endpoint is not None:
                return endpoint

        print("❌ Не удалось найти интерфейс громкости в pycaw.")
        print("   Попробуй: python -m pip install --upgrade pycaw comtypes")
        return None

    except Exception as e:
        print(f"❌ Не удалось получить аудио-устройство: {e}")
        return None


def get_current_volume():
    """
    Возвращает текущую громкость от 0 до 100.
    """
    try:
        audio = get_audio_endpoint()
        if audio is None:
            return None

        volume_scalar = audio.GetMasterVolumeLevelScalar()

        # Некоторые обёртки могут возвращать сразу проценты, а не 0.0–1.0
        if volume_scalar > 1.0:
            return int(round(volume_scalar))

        return int(round(volume_scalar * 100))

    except Exception as e:
        print(f"❌ Не удалось получить громкость: {e}")
        return None


def set_volume(volume_level):
    """
    Устанавливает громкость от 0 до 100 без эмуляции клавиш.
    """
    try:
        if not PYCAW_AVAILABLE:
            print("❌ Не установлен модуль громкости.")
            print("   Выполни: pip install pycaw comtypes")
            if PYCAW_ERROR:
                print(f"   Ошибка импорта: {PYCAW_ERROR}")
            return False

        volume_level = max(0, min(100, int(volume_level)))

        audio = get_audio_endpoint()
        if audio is None:
            return False

        # Если звук был в беззвучном режиме, снимаем его.
        try:
            audio.SetMute(0, None)
        except Exception:
            pass

        audio.SetMasterVolumeLevelScalar(volume_level / 100.0, None)
        return True

    except Exception as e:
        print(f"❌ Ошибка изменения громкости: {e}")
        return False


def change_volume(delta):
    """
    Изменяет громкость относительно текущего уровня.
    Например:
    +10 — громче
    -10 — тише
    """
    try:
        if not PYCAW_AVAILABLE:
            print("❌ Не установлен модуль громкости.")
            print("   Выполни: pip install pycaw comtypes")
            return False

        current_volume = get_current_volume()

        if current_volume is None:
            current_volume = 50

        new_volume = current_volume + int(delta)
        new_volume = max(0, min(100, new_volume))

        return set_volume(new_volume)

    except Exception as e:
        print(f"❌ Ошибка изменения громкости: {e}")
        return False


def parse_volume_from_text(text):
    """
    Понимает громкость цифрами и словами.
    Например:
      "громкость 30" -> 30
      "громкость шесть" -> 6
      "громкость двадцать пять" -> 25
      "громкость сто" -> 100
    """
    # Сначала ищем обычные цифры
    digits = re.findall(r'\d+', text)
    if digits:
        try:
            return int(digits[0])
        except Exception:
            pass

    units = {
        'ноль': 0,
        'нуль': 0,
        'один': 1,
        'одна': 1,
        'одну': 1,
        'два': 2,
        'две': 2,
        'три': 3,
        'четыре': 4,
        'пять': 5,
        'шесть': 6,
        'семь': 7,
        'восемь': 8,
        'девять': 9,
    }

    teens = {
        'десять': 10,
        'одиннадцать': 11,
        'двенадцать': 12,
        'тринадцать': 13,
        'четырнадцать': 14,
        'пятнадцать': 15,
        'шестнадцать': 16,
        'семнадцать': 17,
        'восемнадцать': 18,
        'девятнадцать': 19,
    }

    tens = {
        'двадцать': 20,
        'тридцать': 30,
        'сорок': 40,
        'пятьдесят': 50,
        'шестьдесят': 60,
        'семьдесят': 70,
        'восемьдесят': 80,
        'девяносто': 90,
        'полтинник': 50,
        'полста': 50,
    }

    hundred = {
        'сто': 100,
        'сотка': 100,
        'сотню': 100,
    }

    tokens = re.findall(r'[а-яё]+', text.lower())

    current_tens = None
    last_unit = None

    for token in tokens:
        if token in hundred:
            return 100

        if token in tens:
            current_tens = tens[token]
            last_unit = None
            continue

        if token in teens:
            return teens[token]

        if token in units:
            num = units[token]

            if num == 0:
                if current_tens is not None:
                    return current_tens
                return 0

            if current_tens is not None:
                return current_tens + num

            last_unit = num
            continue

    if current_tens is not None:
        return current_tens

    if last_unit is not None:
        return last_unit

    return None


def speak(text):
    if voice_enabled:
        try:
            safe_text = text.replace('"', '""').replace("'", "''")
            ps_command = f'Add-Type -AssemblyName System.Speech; $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; $synth.Rate = 4; $synth.SelectVoice("Microsoft Pavel"); $synth.Speak("{safe_text}")'
            subprocess.run(
                ['powershell', '-command', ps_command],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception as e:
            print(f"⚠ Ошибка озвучки: {e}")


def is_process_running(process_name):
    try:
        result = subprocess.run(
            ['tasklist', '/FI', f'IMAGENAME eq {process_name}'],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return process_name.lower() in result.stdout.lower()
    except:
        return False


def launch_program(path):
    subprocess.Popen(
        [path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW
    )


def kill_process(process_name):
    try:
        subprocess.run(
            ['taskkill', '/F', '/IM', process_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return True
    except:
        return False


def shutdown_system(action):
    try:
        if action == "shutdown":
            subprocess.run(['shutdown', '/s', '/t', '10'], creationflags=subprocess.CREATE_NO_WINDOW)
            print("🔴 Ноутбук выключится через 10 секунд!")
            speak("Ноутбук выключится через 10 секунд")
        elif action == "restart":
            subprocess.run(['shutdown', '/r', '/t', '10'], creationflags=subprocess.CREATE_NO_WINDOW)
            print("🔄 Ноутбук перезагрузится через 10 секунд!")
            speak("Ноутбук перезагрузится через 10 секунд")
        return True
    except:
        return False


def cancel_shutdown():
    try:
        subprocess.run(['shutdown', '/a'], creationflags=subprocess.CREATE_NO_WINDOW)
        print("✅ Действие отменено!")
        speak("Действие отменено")
        return True
    except:
        return False


def sleep_system():
    try:
        result = ctypes.windll.PowrProf.SetSuspendState(False, True, False)
        return result != 0
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False


def minimize_all():
    try:
        subprocess.run(
            ['powershell', '-command', '(New-Object -ComObject Shell.Application).MinimizeAll()'],
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return True
    except Exception as e:
        print(f"❌ Ошибка сворачивания: {e}")
        return False


def restore_all():
    try:
        subprocess.run(
            ['powershell', '-command', '(New-Object -ComObject Shell.Application).UndoMinimizeALL()'],
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return True
    except Exception as e:
        print(f"❌ Ошибка разворачивания: {e}")
        return False


def take_screenshot():
    try:
        screenshots_dir = os.path.expanduser("~/Pictures/Screenshots")
        if not os.path.exists(screenshots_dir):
            os.makedirs(screenshots_dir)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{timestamp}.png"
        filepath = os.path.join(screenshots_dir, filename)
        ps_filepath = filepath.replace("\\", "\\\\")

        ps_script = f'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bitmap = New-Object System.Drawing.Bitmap($screen.Width, $screen.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size)
$bitmap.Save("{ps_filepath}")
$graphics.Dispose()
$bitmap.Dispose()
'''

        subprocess.run(
            ['powershell', '-command', ps_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        if os.path.exists(filepath):
            return True, filepath
        else:
            return False, None

    except Exception as e:
        print(f"❌ Ошибка скриншота: {e}")
        return False, None


def play_success_sound():
    if not voice_enabled:
        try:
            winsound.PlaySound("DeviceConnect", winsound.SND_ALIAS)
        except:
            winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS)


def play_exit_sound():
    try:
        winsound.PlaySound("SystemExit", winsound.SND_ALIAS)
    except:
        pass


def play_error_sound():
    if not voice_enabled:
        try:
            winsound.PlaySound("SystemHand", winsound.SND_ALIAS)
        except:
            pass


def split_commands(text):
    """Разделяет фразу на отдельные команды по союзам и запятым."""
    parts = re.split(r'\s+и\s+|\s+а\s+|\s+также\s+|\s+потом\s+|\s+затем\s+|,\s*', text)
    return [p.strip() for p in parts if p.strip()]


# ============================================
# НАПОМИНАНИЯ / ТАЙМЕРЫ
# ============================================

active_reminders = []


def normalize_reminder_numbers(text):
    """
    Преобразует простые русские числа в цифры,
    чтобы понимались фразы вроде:
    "напомни через пять минут"
    """
    words = {
        'одну': '1',
        'один': '1',
        'одна': '1',
        'два': '2',
        'две': '2',
        'три': '3',
        'четыре': '4',
        'пять': '5',
        'шесть': '6',
        'семь': '7',
        'восемь': '8',
        'девять': '9',
        'десять': '10',
        'пятнадцать': '15',
        'двадцать': '20',
        'тридцать': '30',
        'сорок': '40',
        'пятьдесят': '50',
    }

    for word, num in words.items():
        text = re.sub(rf'\b{word}\b', num, text, flags=re.I)

    return text


def parse_reminder_time(raw_text):
    """
    Пытается понять время напоминания.
    Возвращает (секунды, красивое описание).
    """
    text = normalize_reminder_numbers(raw_text)

    # Точное время: "в 15:30", "на 15.30", "15-30"
    m = re.search(r'(?:в|на)\s*(\d{1,2})[:.\-](\d{2})', text)

    # Если просто сказали "15:30"
    if not m:
        m = re.search(r'(?<!\d)(\d{1,2})[:.\-](\d{2})(?!\d)', text)

    # Вариант "в 15 30"
    if not m:
        m = re.search(r'(?:в|на)\s*(\d{1,2})\s+(\d{2})\b', text)

    # Вариант "в 15 часов 30 минут"
    if not m:
        m = re.search(
            r'(?:в|на)\s*(\d{1,2})\s*час(?:ов|а)?\s*(\d{1,2})\s*минут',
            text
        )

    if m:
        try:
            hour = int(m.group(1))
            minute = int(m.group(2))

            if 0 <= hour <= 23 and 0 <= minute <= 59:
                now = datetime.now()
                target = now.replace(
                    hour=hour,
                    minute=minute,
                    second=0,
                    microsecond=0
                )

                # Если время уже прошло — ставим на завтра
                if target <= now:
                    target += timedelta(days=1)

                seconds = int((target - now).total_seconds())

                if seconds > 0:
                    return seconds, target.strftime("на %H:%M")

        except Exception:
            pass

    # "полчаса"
    if "полчаса" in text or "пол часа" in text:
        return 30 * 60, "через 30 минут"

    # "через час" / "на час"
    if re.search(r'(?:через|на)\s+час\b', text) or text.strip() == "час":
        return 3600, "через 1 час"

    # "через минуту" / "на минуту"
    if re.search(r'(?:через|на)\s+минуту\b', text):
        return 60, "через 1 минуту"

    # Обычный таймер: "через 5 минут", "таймер на 10 секунд"
    m = re.search(
        r'(\d+)\s*'
        r'(секунд|секунды|сек|с|минут|минута|минуту|мин|м|час|часа|часов|ч)\b',
        text
    )

    if m:
        value = int(m.group(1))
        unit = m.group(2).lower()

        if value <= 0:
            return None, None

        if unit.startswith("с"):
            return value, f"через {value} секунд"

        if unit.startswith("м"):
            return value * 60, f"через {value} минут"

        if unit.startswith("ч"):
            return value * 3600, f"через {value} часов"

    return None, None


def cancel_reminders():
    """Отменяет все активные напоминания."""
    global active_reminders

    cancelled = 0

    for timer in active_reminders:
        try:
            if timer.is_alive():
                timer.cancel()
                cancelled += 1
        except Exception:
            pass

    active_reminders = []
    return cancelled


def show_reminder_window(reason):
    """
    Сворачивает все окна и показывает окно с причиной.
    После закрытия окна все окна разворачиваются обратно.
    """
    # Сначала сворачиваем все окна
    try:
        minimize_all()
        time.sleep(0.4)
    except Exception:
        pass

    # Звук напоминания
    try:
        winsound.PlaySound(
            "SystemExclamation",
            winsound.SND_ALIAS | winsound.SND_ASYNC
        )
    except Exception:
        pass

    # Голосовое уведомление
    try:
        speak("Напоминание")
    except Exception:
        pass

    message = (
        "Сработало напоминание/таймер.\n\n"
        f"Почему открыто окно:\n{reason}\n\n"
        f"Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
    )

    # MB_ICONINFORMATION = 0x00000040
    # MB_TOPMOST = 0x00040000
    try:
        ctypes.windll.user32.MessageBoxW(
            0,
            message,
            "Напоминание",
            0x00000040 | 0x00040000
        )
    except Exception as e:
        print(f"❌ Не удалось показать окно напоминания: {e}")
    finally:
        # После закрытия окна разворачиваем все окна обратно
        try:
            restore_all()
        except Exception:
            pass


def schedule_reminder(text):
    """
    Ставит напоминание/таймер.
    """
    seconds, when_text = parse_reminder_time(text)

    if seconds is None or seconds <= 0:
        return False

    reason = text.strip()

    timer = threading.Timer(
        seconds,
        show_reminder_window,
        args=(reason,)
    )

    timer.daemon = True
    timer.start()

    active_reminders.append(timer)

    print(f"⏰ Напоминание установлено: {when_text}")
    print(f"   Причина: {reason}")

    speak(f"Напоминание установлено {when_text}")
    play_success_sound()

    return True


def process_command(text):
    """Обрабатывает ОДНУ команду. Возвращает True если команда распознана."""
    global last_youtube_open_time, last_qwen_open_time, last_music_open_time, voice_enabled

    # ============================================
    # ОТМЕНА НАПОМИНАНИЙ / ТАЙМЕРОВ
    # ============================================
    if ("отмени" in text or "отменить" in text or "стоп" in text) and ("напомин" in text or "таймер" in text):
        cancelled = cancel_reminders()

        if cancelled:
            print(f"⏹ Отменено напоминаний: {cancelled}")
            speak(f"Отменено напоминаний: {cancelled}")
        else:
            print("⚠ Активных напоминаний нет")
            speak("Активных напоминаний нет")

        play_success_sound()
        return True

    # ============================================
    # НАПОМИНАНИЕ / ТАЙМЕР
    # ============================================
    if "напомин" in text or "таймер" in text or "поставь время" in text or "выстави время" in text:
        if schedule_reminder(text):
            return True

        print("⚠ Не понял формат напоминания.")
        speak("Скажи, например: напомни через 5 минут пить чай")
        play_error_sound()
        return True

    # ============================================
    # МУЗЫКА / YOUTUBE MUSIC
    # ============================================
    music_exact = text.strip() in [
        "музыка",
        "музыку",
        "включи музыку",
        "открой музыку",
        "music",
        "мьюзик"
    ]

    music_trigger = (
        "открой музыку" in text or
        "включи музыку" in text or
        "открой ютуб музыку" in text or
        "ютуб музыка" in text or
        "ютьуб музыка" in text or
        "youtube music" in text or
        "открой music" in text or
        "музыка ютуб" in text or
        "открой ютуб мьюзик" in text or
        "ютуб мьюзик" in text or
        "включи ютуб музыку" in text or
        "включи ютуб мьюзик" in text or
        "открой мьюзик" in text or
        "мьюзик" in text
    )

    if music_exact or music_trigger:
        current_time = time.time()
        time_since_last_open = current_time - last_music_open_time

        if time_since_last_open < MUSIC_COOLDOWN:
            remaining_time = int(MUSIC_COOLDOWN - time_since_last_open)
            print(f"⚠ YouTube Music уже был открыт недавно. Подождите еще {remaining_time} сек.")
            speak(f"Музыка уже была открыта, подождите {remaining_time} секунд")
            play_error_sound()
        else:
            print("🎵 Открываю YouTube Music...")
            webbrowser.open(music_url)
            last_music_open_time = current_time
            print("✅ YouTube Music открыт в браузере!")
            speak("Музыка открыта")
            play_success_sound()
            time.sleep(0.5)

        return True

    # Команда ОТКРЫТЬ игру
    if "открой танки" in text or "запусти танки" in text:
        if is_process_running(game_process_name):
            print("⚠ Игра уже запущена!")
            speak("Игра уже запущена")
            play_error_sound()
        elif os.path.exists(game_path):
            launch_program(game_path)
            print("🎮 Игра запущена!")
            speak("Игра запущена")
            play_success_sound()
            time.sleep(0.5)
        else:
            print(f"❌ Файл не найден: {game_path}")
            speak("Файл игры не найден")
            play_error_sound()
        return True

    # Команда ЗАКРЫТЬ игру
    elif "закрой танки" in text or "выключи танки" in text or "убей танки" in text:
        if is_process_running(game_process_name):
            kill_process(game_process_name)
            print("🛑 Игра закрыта!")
            speak("Игра закрыта")
            play_success_sound()
            time.sleep(0.5)
        else:
            print("⚠ Игра не запущена.")
            speak("Игра не запущена")
            play_error_sound()
        return True

    # YouTube
    elif "открой ютуб" in text or "ютуб" in text or "открой youtube" in text or "youtube" in text or "ютюб" in text:
        current_time = time.time()
        time_since_last_open = current_time - last_youtube_open_time

        if time_since_last_open < YOUTUBE_COOLDOWN:
            remaining_time = int(YOUTUBE_COOLDOWN - time_since_last_open)
            print(f"⚠ YouTube уже был открыт недавно. Подождите еще {remaining_time} сек.")
            speak(f"YouTube уже был открыт, подождите {remaining_time} секунд")
            play_error_sound()
        else:
            print("🌐 Открываю YouTube...")
            webbrowser.open(youtube_url)
            last_youtube_open_time = current_time
            print("✅ YouTube открыт в браузере!")
            speak("YouTube открыт")
            play_success_sound()
            time.sleep(0.5)
        return True

    # Qwen
    elif ("открой qwen" in text or "qwen" in text or "квен" in text or
          "запусти qwen" in text or "queen" in text or "квин" in text or
          "квн" in text or "открой квин" in text or "открой квен" in text or
          "открой квн" in text or "открой queen" in text):
        current_time = time.time()
        time_since_last_open = current_time - last_qwen_open_time

        if time_since_last_open < QWEN_COOLDOWN:
            remaining_time = int(QWEN_COOLDOWN - time_since_last_open)
            print(f"⚠ Qwen уже был открыт недавно. Подождите еще {remaining_time} сек.")
            speak(f"Qwen уже был открыт, подождите {remaining_time} секунд")
            play_error_sound()
        else:
            print("🤖 Открываю Qwen...")
            webbrowser.open(qwen_url)
            last_qwen_open_time = current_time
            print("✅ Qwen открыт в браузере!")
            speak("Qwen открыт")
            play_success_sound()
            time.sleep(0.5)
        return True

    # LM Studio
    elif ("открой эм эль студио" in text or "эм эль студио" in text or
          "открой лм студио" in text or "лм студио" in text or
          "открой эл эм студио" in text or "эл эм студио" in text or
          "lm studio" in text or "открой lm studio" in text or
          "запусти lm studio" in text or "запусти лм студио" in text or
          "открой студио" in text or "studio" in text or "студия" in text or
          "открой студию" in text or "студию" in text or "lm studi" in text or
          "открой lm studi" in text or "запусти студио" in text):
        if os.path.exists(lm_studio_path):
            launch_program(lm_studio_path)
            print("🧠 LM Studio запущена!")
            speak("Эль эм студио запущена")
            play_success_sound()
            time.sleep(0.5)
        else:
            print(f"❌ Файл не найден: {lm_studio_path}")
            speak("Файл не найден")
            play_error_sound()
        return True

    # ============================================
    # ОБХОД
    # ============================================
    elif "запусти обход" in text or "открой обход" in text or "обход" in text:
        obhod_path = None

        for path in obhod_paths:
            if os.path.exists(path):
                obhod_path = path
                break

        if obhod_path:
            try:
                subprocess.Popen(
                    ['cmd', '/c', obhod_path],
                    cwd=os.path.dirname(obhod_path),
                    creationflags=subprocess.CREATE_NEW_CONSOLE
                )

                print(f"🚀 Обход запущен: {obhod_path}")
                speak("Обход запущен")
                play_success_sound()
                time.sleep(0.3)
            except Exception as e:
                print(f"❌ Не удалось запустить обход: {e}")
                speak("Не удалось запустить обход")
                play_error_sound()
        else:
            print("❌ Файл обхода не найден. Проверял пути:")
            for path in obhod_paths:
                print(f"   - {path}")
            speak("Файл обхода не найден")
            play_error_sound()

        return True

    # Диспетчер задач
    elif ("открой диспетчер задач" in text or "диспетчер задач" in text or
          "открой диспетчер" in text or "запусти диспетчер задач" in text or
          "открой таск менеджер" in text or "таск менеджер" in text or
          "task manager" in text):
        try:
            os.startfile('taskmgr.exe')
            print("📊 Диспетчер задач открыт!")
            speak("Диспетчер задач открыт")
            play_success_sound()
            time.sleep(0.3)
        except Exception as e:
            print(f"❌ Не удалось открыть диспетчер задач: {e}")
            speak("Не удалось открыть диспетчер задач")
            play_error_sound()
        return True

    # Закрытие Edge
    elif ("закрой edge" in text or "закрой эдж" in text or
          "закрой браузер" in text or "выключи браузер" in text or
          "закрой edge браузер" in text or "убей браузер" in text or
          "выключи edge" in text or "выключи эдж" in text or
          "закрыть браузер" in text or "закрыть edge" in text):
        if is_process_running(edge_process_name):
            kill_process(edge_process_name)
            print("🌐 Edge закрыт!")
            speak("Браузер закрыт")
            play_success_sound()
            time.sleep(0.3)
        else:
            print("⚠ Edge не запущен.")
            speak("Браузер не запущен")
            play_error_sound()
        return True

    # Громче / тише
    elif "громче" in text:
        if change_volume(10):
            print("🔊 Громкость увеличена на 10%")
            speak("Громкость увеличена")
            play_success_sound()
        else:
            print("❌ Не удалось увеличить громкость")
            speak("Не удалось увеличить громкость")
            play_error_sound()
        return True

    elif "тише" in text:
        if change_volume(-10):
            print("🔉 Громкость уменьшена на 10%")
            speak("Громкость уменьшена")
            play_success_sound()
        else:
            print("❌ Не удалось уменьшить громкость")
            speak("Не удалось уменьшить громкость")
            play_error_sound()
        return True

    # Громкость
    elif "громкость" in text:
        volume = parse_volume_from_text(text)

        if volume is not None:
            if 0 <= volume <= 100:
                if set_volume(volume):
                    print(f"🔊 Громкость установлена на {volume}%")
                    speak(f"Громкость {volume} процентов")
                    play_success_sound()
                else:
                    print("❌ Не удалось изменить громкость")
                    speak("Не удалось изменить громкость")
                    play_error_sound()
            else:
                print(f"⚠ Громкость должна быть от 0 до 100 (ты сказал {volume})")
                speak("Громкость должна быть от 0 до 100")
                play_error_sound()
        else:
            print("⚠ Скажи число, например: 'громкость 50' или 'громкость шесть'")
            speak("Скажи число, например громкость 50 или громкость шесть")
            play_error_sound()

        return True

    # Папки
    elif "открой загрузки" in text or "открой папку загрузки" in text:
        try:
            downloads_path = os.path.expanduser("~/Downloads")
            os.startfile(downloads_path)
            print("📁 Папка Загрузки открыта!")
            speak("Папка загрузки открыта")
            play_success_sound()
            time.sleep(0.3)
        except Exception as e:
            print(f"❌ Не удалось открыть папку: {e}")
            speak("Не удалось открыть папку")
            play_error_sound()
        return True

    elif "открой документы" in text or "открой папку документы" in text:
        try:
            documents_path = os.path.expanduser("~/Documents")
            os.startfile(documents_path)
            print("📁 Папка Документы открыта!")
            speak("Папка документы открыта")
            play_success_sound()
            time.sleep(0.3)
        except Exception as e:
            print(f"❌ Не удалось открыть папку: {e}")
            speak("Не удалось открыть папку")
            play_error_sound()
        return True

    elif "открой рабочий стол" in text or "открой папку рабочий стол" in text:
        try:
            desktop_path = os.path.expanduser("~/Desktop")
            os.startfile(desktop_path)
            print("🖥️ Рабочий стол открыт!")
            speak("Рабочий стол открыт")
            play_success_sound()
            time.sleep(0.3)
        except Exception as e:
            print(f"❌ Не удалось открыть папку: {e}")
            speak("Не удалось открыть папку")
            play_error_sound()
        return True

    elif "открой изображения" in text or "открой картинки" in text or "открой папку изображения" in text:
        try:
            pictures_path = os.path.expanduser("~/Pictures")
            os.startfile(pictures_path)
            print("🖼️ Папка Изображения открыта!")
            speak("Папка изображения открыта")
            play_success_sound()
            time.sleep(0.3)
        except Exception as e:
            print(f"❌ Не удалось открыть папку: {e}")
            speak("Не удалось открыть папку")
            play_error_sound()
        return True

    # Медиа
    elif "пауза" in text or "поставь на паузу" in text or "останови музыку" in text or "выключи музыку" in text:
        keyboard.press_and_release('play/pause')
        print("⏸️ Пауза")
        speak("Пауза")
        play_success_sound()
        time.sleep(0.3)
        return True

    elif "играй" in text or "продолжить" in text or "возобнови" in text or "продолжай" in text:
        keyboard.press_and_release('play/pause')
        print("▶️ Играет")
        speak("Играет")
        play_success_sound()
        time.sleep(0.3)
        return True

    elif "следующий трек" in text or "следующая песня" in text or "переключи" in text or "далее" in text or "дальше" in text:
        keyboard.press_and_release('next track')
        print("⏭️ Следующий трек")
        speak("Следующий трек")
        play_success_sound()
        time.sleep(0.3)
        return True

    elif "предыдущий трек" in text or "предыдущая песня" in text or "назад" in text:
        keyboard.press_and_release('previous track')
        print("⏮️ Предыдущий трек")
        speak("Предыдущий трек")
        play_success_sound()
        time.sleep(0.3)
        return True

    # Окна
    elif "сверни всё" in text or "сверни все" in text or "свернуть всё" in text or "свернуть все" in text:
        if minimize_all():
            print("🗔 Все окна свёрнуты")
            speak("Все окна свёрнуты")
            play_success_sound()
            time.sleep(0.3)
        else:
            print("❌ Не удалось свернуть окна")
            speak("Не удалось свернуть окна")
            play_error_sound()
        return True

    elif "разверни всё" in text or "разверни все" in text or "развернуть всё" in text or "развернуть все" in text:
        if restore_all():
            print("🗕 Все окна развёрнуты")
            speak("Все окна развёрнуты")
            play_success_sound()
            time.sleep(0.3)
        else:
            print("❌ Не удалось развернуть окна")
            speak("Не удалось развернуть окна")
            play_error_sound()
        return True

    # Скриншот
    elif "сделай скриншот" in text or "скриншот" in text or "скрин" in text or "сними экран" in text:
        success, filepath = take_screenshot()
        if success:
            print(f"📸 Скриншот сохранён: {filepath}")
            speak("Скриншот сделан и сохранён")
            play_success_sound()
            time.sleep(0.3)
        else:
            print("❌ Не удалось сделать скриншот")
            speak("Не удалось сделать скриншот")
            play_error_sound()
        return True

    # Озвучка
    elif "включи озвучку" in text or "включи голос" in text:
        voice_enabled = True
        print("🔊 Голосовые ответы включены")
        speak("Голосовые ответы включены")
        play_success_sound()
        time.sleep(0.3)
        return True

    elif "выключи озвучку" in text or "выключи голос" in text or "без звука" in text:
        voice_enabled = False
        print("🔇 Голосовые ответы выключены")
        play_success_sound()
        time.sleep(0.3)
        return True

    # Перезагрузка
    elif "перезагрузи ноутбук" in text or "перезагрузи" in text or "перезагрузка" in text or "рестарт" in text:
        print("⚠ ВНИМАНИЕ: Ноутбук перезагрузится через 10 секунд!")
        print("   Скажи 'отмена' чтобы отменить")
        play_error_sound()
        time.sleep(1)
        shutdown_system("restart")
        return True

    # Выключение
    elif "выключи ноутбук" in text or "выключи комп" in text or "выключи компьютер" in text or "shutdown" in text:
        print("⚠ ВНИМАНИЕ: Ноутбук выключится через 10 секунд!")
        print("   Скажи 'отмена' чтобы отменить")
        play_error_sound()
        time.sleep(1)
        shutdown_system("shutdown")
        return True

    # Сон
    elif "сон" in text or "спящий режим" in text or "усыпи" in text or "усыпи ноутбук" in text:
        print("😴 Ноутбук уходит в спящий режим...")
        speak("Ноутбук уходит в спящий режим")
        play_exit_sound()
        time.sleep(0.5)
        if sleep_system():
            print("✅ Спящий режим активирован!")
        else:
            print("⚠ Не удалось перевести в спящий режим.")
            speak("Не удалось перевести в спящий режим")
        return True

    # Отмена
    elif "отмена" in text or "отмени" in text or "стоп выключение" in text:
        cancel_shutdown()
        time.sleep(0.3)
        return True

    # Выход
    elif "выход" in text or "стоп" in text or "завершить" in text:
        print("👋 Завершаю работу скрипта...")
        speak("Завершаю работу")
        play_exit_sound()
        return "EXIT"

    return False


def manual_input_loop():
    """
    Позволяет вводить команды вручную через консоль,
    пока голосовой ассистент продолжает слушать.
    """
    while not manual_exit_event.is_set():
        try:
            cmd = input("⌨ Введите команду вручную: ")
        except EOFError:
            break
        except KeyboardInterrupt:
            break

        cmd = cmd.strip().lower()

        if not cmd:
            continue

        if cmd in ["exit", "quit"]:
            print("👋 Завершаю работу скрипта...")
            manual_exit_event.set()
            break

        print(f"⌨ Вы ввели: {cmd}")

        commands = split_commands(cmd)
        should_exit = False

        for one_command in commands:
            with command_lock:
                result = process_command(one_command)

            if result == "EXIT":
                should_exit = True
                break

        if should_exit:
            manual_exit_event.set()
            break


print("Скрипт запущен. Доступные команды:")
print("  - 'открой танки' - запустить игру")
print("  - 'закрой танки' - закрыть игру")
print("  - 'открой ютуб' / 'открой youtube' - открыть YouTube")
print("  - 'открой музыку' / 'музыка' - открыть YouTube Music")
print("  - 'открой квен' / 'открой квин' - открыть Qwen")
print("  - 'открой эм эль студио' / 'открой студио' - открыть LM Studio")
print("  - 'запусти обход' / 'обход' - запустить обход")
print("  - 'открой диспетчер задач' - открыть диспетчер задач")
print("  - 'закрой edge' / 'закрой браузер' - закрыть Edge")
print("  - 'громкость 50' / 'громкость шесть' - установить громкость")
print("  - 'громче' - увеличить громкость на 10%")
print("  - 'тише' - уменьшить громкость на 10%")
print("  - 'открой загрузки' / 'документы' / 'рабочий стол' / 'изображения'")
print("  - 'пауза' / 'играй' - управление музыкой")
print("  - 'следующий трек' / 'дальше' - следующий трек")
print("  - 'предыдущий трек' / 'назад' - предыдущий трек")
print("  - 'сверни всё' / 'разверни всё' - управление окнами")
print("  - 'сделай скриншот' / 'скрин' - скриншот")
print("  - 'включи озвучку' / 'выключи озвучку' - голос")
print("  - 'перезагрузи ноутбук' / 'выключи ноутбук' / 'сон'")
print("  - 'напомни через 5 минут' / 'таймер на 2 минуты' - напоминания")
print("  - 'отмени таймер' / 'отмени напоминание' - отмена напоминаний")
print("  - 'отмена' / 'выход'")
print("")
print("💡 Можно говорить НЕСКОЛЬКО команд через 'и':")
print("   Пример: 'громкость 30 и открой ютуб'")
print("   Пример: 'открой танки и закрой edge'")
print("")
print("💡 Также команды можно писать вручную прямо в консоли.")

manual_thread = threading.Thread(target=manual_input_loop, daemon=True)
manual_thread.start()

play_success_sound()
speak("Ассистент запущен и готов к работе")

while True:
    if manual_exit_event.is_set():
        break

    with sr.Microphone() as source:
        print("🎧 Слушаю команду...")
        r.adjust_for_ambient_noise(source, duration=0.5)

        try:
            audio = r.listen(source, timeout=3, phrase_time_limit=8)
        except sr.WaitTimeoutError:
            continue

        try:
            text = r.recognize_google(audio, language='ru').lower()
            print(f"🗣 Вы сказали: {text}")

            # Разделяем фразу на отдельные команды
            commands = split_commands(text)

            if len(commands) > 1:
                print(f"📋 Распознано {len(commands)} команды: {commands}")

            # Обрабатываем каждую команду по очереди
            any_recognized = False
            should_exit = False

            for cmd in commands:
                if manual_exit_event.is_set():
                    should_exit = True
                    break

                with command_lock:
                    result = process_command(cmd)

                if result == "EXIT":
                    should_exit = True
                    break
                elif result:
                    any_recognized = True

            if should_exit:
                break

            if not any_recognized and len(commands) == 1:
                pass

        except sr.UnknownValueError:
            print("Не понято")
        except sr.RequestError:
            print("Ошибка соединения с API")