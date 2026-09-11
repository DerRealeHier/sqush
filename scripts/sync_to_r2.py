# sync all local games & covers to cloudflare r2 so players can actually download stuff (:
import os
import sys
import re
import mimetypes
from dotenv import load_dotenv

load_dotenv()

try:
    import boto3
    from botocore.config import Config
except ImportError:
    print("boto3 is missing! run: pip install boto3")
    sys.exit(1)


def get_endpoint(account_id):
    raw = (account_id or "").strip()
    cleaned = re.sub(r"^(https?[:/]+)+", "", raw, flags=re.IGNORECASE).strip("/")
    if not cleaned:
        return ""
    if ".r2.cloudflarestorage.com" in cleaned:
        return f"https://{cleaned}"
    return f"https://{cleaned}.r2.cloudflarestorage.com"


def main():
    print("--- sqush r2 sync tool xD ---")

    account_id = os.environ.get("R2_ACCOUNT_ID")
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    bucket_name = os.environ.get("R2_BUCKET_NAME", "sqush-games")

    if not account_id:
        account_id = input("R2 Account ID (e.g. 7d7d33fb1dc25e582b28036860c30c00): ").strip()
    if not access_key:
        access_key = input("R2 Access Key ID: ").strip()
    if not secret_key:
        import getpass
        secret_key = getpass.getpass("R2 Secret Access Key: ").strip()

    endpoint = get_endpoint(account_id)
    print(f"connecting to: {endpoint}")
    print(f"target bucket: {bucket_name}")

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )

    try:
        client.head_bucket(Bucket=bucket_name)
        print(f"bucket '{bucket_name}' found and ready to rumble (: \n")
    except Exception as e:
        print(f"could not access bucket '{bucket_name}': {e}")
        print("check your credentials and bucket name, bro!")
        sys.exit(1)

    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "uploads"))
    if not os.path.exists(root_dir):
        print(f"folder {root_dir} not found!")
        sys.exit(1)

    files_to_upload = []
    for root, dirs, files in os.walk(root_dir):
        for f in files:
            if f == ".gitkeep":
                continue
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, os.path.join(root_dir, "..")).replace("\\", "/")
            files_to_upload.append((full_path, rel_path))

    total = len(files_to_upload)
    print(f"found {total} files to sync (: let's pump them to r2!\n")

    uploaded = 0
    skipped = 0

    for idx, (full_path, r2_key) in enumerate(files_to_upload, 1):
        file_size = os.path.getsize(full_path)
        size_mb = file_size / (1024 * 1024)

        try:
            head = client.head_object(Bucket=bucket_name, Key=r2_key)
            if head.get("ContentLength") == file_size:
                print(f"[{idx}/{total}] already in r2: {r2_key} ({size_mb:.2f} MB) - skipped (:")
                skipped += 1
                continue
        except Exception:
            pass

        content_type, _ = mimetypes.guess_type(full_path)
        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type

        print(f"[{idx}/{total}] uploading: {r2_key} ({size_mb:.2f} MB)...", end="", flush=True)
        try:
            client.upload_file(full_path, bucket_name, r2_key, ExtraArgs=extra_args)
            print(" DONE! :D")
            uploaded += 1
        except Exception as err:
            print(f" FAILED ): ({err})")

    print("\n--- all done! ---")
    print(f"uploaded: {uploaded}")
    print(f"skipped (already there): {skipped}")
    print("now players can download games from r2 without crying xD\n")


if __name__ == "__main__":
    main()
