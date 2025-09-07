import os
import dropbox
import hashlib
import tempfile
import shutil
from dropbox.files import WriteMode, FileMetadata, FolderMetadata
from typing import Optional
from config import APP_KEY, APP_SECRET, REFRESH_TOKEN, logger

if not (APP_KEY and APP_SECRET and REFRESH_TOKEN):
    raise RuntimeError('Не заданы переменные окружения для Dropbox OAuth2!')

dbx = dropbox.Dropbox(
    oauth2_refresh_token=REFRESH_TOKEN,
    app_key=APP_KEY,
    app_secret=APP_SECRET,
)

def upload_file(local_path: str, dropbox_path: str) -> Optional[str]:
    try:
        with open(local_path, 'rb') as f:
            dbx.files_upload(f.read(), dropbox_path, mode=WriteMode.overwrite)
        return dropbox_path
    except Exception as e:
        logger.error(f'Ошибка загрузки {local_path}: {str(e)}')
        return None

def download_file(dropbox_path: str, local_path: str) -> bool:
    try:
        metadata, response = dbx.files_download(dropbox_path)
        if response is None:
            logger.error(f'Ошибка скачивания {dropbox_path}: пустой ответ от Dropbox')
            return False
        with open(local_path, 'wb') as f:
            f.write(response.content)
        return True
    except Exception as e:
        logger.error(f'Ошибка скачивания {dropbox_path}: {str(e)}')
        return False

def delete_file(dropbox_path: str) -> bool:
    try:
        dbx.files_delete_v2(dropbox_path)
        return True
    except Exception as e:
        logger.error(f'Ошибка удаления {dropbox_path}: {str(e)}')
        return False

def file_content_hash(path):
    block_size = 4 * 1024 * 1024
    hasher = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            block = f.read(block_size)
            if not block:
                break
            hasher.update(hashlib.sha256(block).digest())
    return hasher.hexdigest()

def sync_resources_hash():
    """
    Синхронизирует папку resources с Dropbox по хешам:
    - Скачивает только новые/изменённые файлы
    - Удаляет локальные файлы, которых нет в Dropbox
    - Не трогает совпадающие
    """
    def _sync(dropbox_folder, local_folder):
        os.makedirs(local_folder, exist_ok=True)
        try:
            result = dbx.files_list_folder(dropbox_folder)
            if result is None:
                logger.error(f'Ошибка при хеш-синхронизации папки {dropbox_folder}: пустой ответ от Dropbox')
                return
            entries = getattr(result, 'entries', [])
            dropbox_files = {}
            dropbox_folders = set()
            for entry in entries:
                dropbox_path = entry.path_lower
                local_path = os.path.join(local_folder, entry.name)
                if isinstance(entry, FileMetadata):
                    dropbox_files[entry.name] = entry.content_hash
                elif isinstance(entry, FolderMetadata):
                    dropbox_folders.add(entry.name)
                    _sync(dropbox_path, local_path)
            for fname, dbx_hash in dropbox_files.items():
                local_path = os.path.join(local_folder, fname)
                if not os.path.exists(local_path):
                    metadata, response = dbx.files_download(f"{dropbox_folder}/{fname}")
                    if response is None:
                        logger.error(f'Ошибка скачивания файла {dropbox_folder}/{fname}: пустой ответ от Dropbox')
                        continue
                    with open(local_path, 'wb') as f:
                        f.write(response.content)
                else:
                    try:
                        local_hash = file_content_hash(local_path)
                    except Exception:
                        local_hash = None
                    if local_hash != dbx_hash:
                        metadata, response = dbx.files_download(f"{dropbox_folder}/{fname}")
                        if response is None:
                            logger.error(f'Ошибка скачивания файла {dropbox_folder}/{fname}: пустой ответ от Dropbox')
                            continue
                        with open(local_path, 'wb') as f:
                            f.write(response.content)
            for fname in os.listdir(local_folder):
                fpath = os.path.join(local_folder, fname)
                if os.path.isfile(fpath) and fname not in dropbox_files:
                    os.remove(fpath)
                elif os.path.isdir(fpath) and fname not in dropbox_folders:
                    shutil.rmtree(fpath)
        except Exception as e:
            logger.error(f'Ошибка при хеш-синхронизации папки {dropbox_folder}: {str(e)}')
    # Сначала переименовываем только фоны и рисунки
    rename_and_sync_dropbox_images('/resources/images')
    rename_and_sync_dropbox_images('/resources/backgrounds')
    _sync('/resources', 'resources')

def rename_and_sync_dropbox_images(dropbox_folder: str):
    """
    Переименовывает все изображения в папке Dropbox по порядку: 1.jpg, 2.jpg, ... (с сохранением расширения).
    Если имена уже идут по порядку, ничего не делает.
    Работает для .jpg, .jpeg, .png, .gif
    """
    exts = ['.jpg', '.jpeg', '.png', '.gif']
    try:
        result = dbx.files_list_folder(dropbox_folder)
        if result is None:
            logger.error(f'Ошибка при переименовании файлов на Dropbox в {dropbox_folder}: пустой ответ от Dropbox')
            return
        entries = getattr(result, 'entries', [])
        files = [entry for entry in entries if isinstance(entry, FileMetadata) and any(entry.name.lower().endswith(ext) for ext in exts)]
        numeric = []
        non_numeric = []
        for entry in files:
            name_wo_ext = os.path.splitext(entry.name)[0]
            ext = os.path.splitext(entry.name)[1].lower()
            if name_wo_ext.isdigit():
                numeric.append((int(name_wo_ext), entry))
            else:
                non_numeric.append((entry.name.lower(), entry))
        numeric_sorted = [e for _, e in sorted(numeric, key=lambda x: x[0])]
        non_numeric_sorted = [e for _, e in sorted(non_numeric, key=lambda x: x[0])]
        files_sorted = numeric_sorted + non_numeric_sorted
        need_rename = False
        for idx, entry in enumerate(files_sorted, 1):
            ext = os.path.splitext(entry.name)[1].lower()
            expected_name = f"{idx}{ext}"
            if entry.name != expected_name:
                need_rename = True
                break
        if not need_rename:
            return
        tmpdir = tempfile.mkdtemp(prefix='dropbox_images_')
        local_files = []
        for idx, entry in enumerate(files_sorted, 1):
            ext = os.path.splitext(entry.name)[1].lower()
            local_name = f"{idx}{ext}"
            local_path = os.path.join(tmpdir, local_name)
            md, res = dbx.files_download(entry.path_lower)
            with open(local_path, 'wb') as f:
                f.write(res.content)
            local_files.append((local_name, local_path))
        for entry in files:
            dbx.files_delete_v2(entry.path_lower)
        for local_name, local_path in local_files:
            dropbox_path = f"{dropbox_folder}/{local_name}"
            with open(local_path, 'rb') as f:
                dbx.files_upload(f.read(), dropbox_path, mode=WriteMode.overwrite)
        shutil.rmtree(tmpdir)
    except Exception as e:
        logger.error(f'Ошибка при переименовании файлов на Dropbox в {dropbox_folder}: {str(e)}') 
