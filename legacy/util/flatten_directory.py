import os
import shutil

def flatten_directory():
    current_dir = os.getcwd()

    # scan full dir contents
    for entry in os.listdir(current_dir):
        entry_path = os.path.join(current_dir, entry)
        # Only operate on folders
        if os.path.isdir(entry_path):
            for root, _, files in os.walk(entry_path):
                for file in files:
                    src = os.path.join(root, file)
                    dest = os.path.join(current_dir, file)

                    # If destination file exists, rename to avoid overwrite
                    if os.path.exists(dest):
                        base, ext = os.path.splitext(file)
                        counter = 1
                        while os.path.exists(dest):
                            new_name = f"{base}_{counter}{ext}"
                            dest = os.path.join(current_dir, new_name)
                            counter += 1

                    shutil.move(src, dest)

            # After moving all files, delete the now-empty folder
            shutil.rmtree(entry_path)

if __name__ == "__main__":
    flatten_directory()
