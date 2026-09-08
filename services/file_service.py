import os
import clamd
from werkzeug.utils import secure_filename
from flask import current_app
import config


def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in config.ALLOWED_EXTENSIONS


def allowed_game_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in config.ALLOWED_GAME_EXTENSIONS


def get_r2_client():
    if not config.R2_ENABLED:
        return None
    try:
        import boto3
        from botocore.config import Config
        return boto3.client(
            "s3",
            endpoint_url=f"https://{config.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=config.R2_ACCESS_KEY_ID,
            aws_secret_access_key=config.R2_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
    except Exception as e:
        print(f"DEBUG: Could not initialize Cloudflare R2 client: {e}")
        return None


def upload_to_r2(file_stream, key, content_type=None):
    client = get_r2_client()
    if client is None:
        return False
    extra_args = {}
    if content_type:
        extra_args["ContentType"] = content_type
    try:
        file_stream.seek(0)
        client.upload_fileobj(file_stream, config.R2_BUCKET_NAME, key, ExtraArgs=extra_args)
        return True
    except Exception as e:
        print(f"DEBUG: R2 upload error for {key}: {e}")
        return False


def generate_presigned_download_url(key, filename=None, expires_in=3600):
    client = get_r2_client()
    if client is None:
        return None
    params = {
        "Bucket": config.R2_BUCKET_NAME,
        "Key": key,
    }
    if filename:
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
    try:
        return client.generate_presigned_url("get_object", Params=params, ExpiresIn=expires_in)
    except Exception as e:
        print(f"DEBUG: Failed to generate presigned download URL for {key}: {e}")
        return None


def save_file(file, folder=None):
    #the save logic is not duplicated anymore
    target_folder = folder or (current_app.config['UPLOAD_FOLDER'] if current_app else config.UPLOAD_FOLDER)
    if file and file.filename:
        filename = secure_filename(file.filename)
        relative_folder = os.path.basename(target_folder)
        rel_key = f"{relative_folder}/{filename}"

        if config.R2_ENABLED:
            try:
                uploaded = upload_to_r2(file.stream, rel_key, content_type=file.content_type)
                if uploaded:
                    try:
                        file.stream.seek(0)
                        file.save(os.path.join(target_folder, filename))
                    except Exception:
                        pass
                    return rel_key
            except Exception as e:
                print(f"DEBUG: R2 save_file fallback: {e}")

        file.save(os.path.join(target_folder, filename))
        return rel_key
    return None


def get_clamd_client():
    # only one error at a time
    if not config.CLAMAV_ENABLED:
        return None
    try:
        cd = clamd.ClamdNetworkSocket(host=config.CLAMAV_HOST, port=config.CLAMAV_PORT)
        cd.ping()
        return cd
    except Exception as e:
        print(f"DEBUG: Cant reach ClamAV: {e}")
        return None


def scan_filestorage_for_malware(file_storage):

    if not config.CLAMAV_ENABLED:
        print(f"DEBUG: ClamAV deactivated, Scan for {file_storage.filename} skipped")
        return True, "Scan skipped (ClamAV not configured)"

    cd = get_clamd_client()
    if cd is None:
        return False, "Security scanner is currently unavailable, upload rejected"

    try:
        file_storage.stream.seek(0)
        result = cd.instream(file_storage.stream)
        file_storage.stream.seek(0)  # rewind, we still need to file.save() this afterwards xD
    except Exception as e:
        # just so I know if I messed up some configsetting or something.
        print(f"DEBUG: ClamAV instream Fehler: {e}")
        return False, "Security scanner error, upload rejected"

    if not result:
        return True, "Clean"

    status, signature = result.get("stream", (None, None))
    if status == "FOUND":
        return False, f"Malware detected ({signature})"
    return True, "Clean"


def save_game_file(file, folder=None):

    if not file or not file.filename:
        return None, None

    if not allowed_game_file(file.filename):
        return None, "Only .zip or .exe files are allowed here"

    is_clean, message = scan_filestorage_for_malware(file)
    if not is_clean:
        print(f"DEBUG: Upload rejected ({file.filename}): {message}")
        return None, message

    target_folder = folder or (current_app.config['UPLOAD_FOLDER'] if current_app else config.UPLOAD_FOLDER)
    filename = secure_filename(file.filename)
    relative_folder = os.path.basename(target_folder)
    r2_key = f"games/{filename}"

    if config.R2_ENABLED:
        try:
            uploaded = upload_to_r2(file.stream, r2_key, content_type=getattr(file, "content_type", "application/octet-stream"))
            if uploaded:
                return r2_key, None
        except Exception as e:
            print(f"DEBUG: R2 save_game_file failed, falling back to local: {e}")

    full_path = os.path.join(target_folder, filename)
    file.save(full_path)

    return f"{relative_folder}/{filename}", None
