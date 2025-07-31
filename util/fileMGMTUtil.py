import os
import re
import shlex
import shutil

current_dir = os.getcwd()



def expand_year_range(filename):
    """
    Extracts start and end years and returns a list of (year, new filename).
    Example: Report_2018-2020.csv → [Report_2018.csv, Report_2019.csv, Report_2020.csv]
    """
    match = re.match(r"(.*?)(\d{4})[-_](\d{4})(\.[a-zA-Z0-9]+)$", filename)
    if not match:
        return None

    base, start_year, end_year, ext = match.groups()
    try:
        years = range(int(start_year), int(end_year) + 1)
        return [f"{base}{year}{ext}" for year in years]
    except ValueError:
        return None

# Converts 1 file covering X years to X files covering 1 year
def expand_file(filename):
    source_path = os.path.join(current_dir, filename)
    if not os.path.isfile(source_path):
        print(f"Error: '{filename}' is not a valid file.")
        return

    new_filenames = expand_year_range(filename)
    if not new_filenames:
        print("Filename must match format like name_YYYY-YYYY.ext or name_YYYY_YYYY.ext")
        return

    for new_file in new_filenames:
        dest_path = os.path.join(current_dir, new_file)
        shutil.copy2(source_path, dest_path)
        print(f"Created: {dest_path}")


# Simple find and replace all operation on filenames, allows subfolder search by argument
def find_and_replace_filenames(find_str, replace_str, recursive=False):
    count = 0
    if recursive:
        for dirpath, _, filenames in os.walk(current_dir):
            for filename in filenames:
                if find_str in filename:
                    old_path = os.path.join(dirpath, filename)
                    new_filename = filename.replace(find_str, replace_str)
                    new_path = os.path.join(dirpath, new_filename)
                    os.rename(old_path, new_path)
                    print(f"Renamed: {old_path} → {new_path}")
                    count += 1
    else:
        for filename in os.listdir(current_dir):
            full_path = os.path.join(current_dir, filename)
            if os.path.isfile(full_path) and find_str in filename:
                new_filename = filename.replace(find_str, replace_str)
                new_path = os.path.join(current_dir, new_filename)
                os.rename(full_path, new_path)
                print(f"Renamed: {full_path} → {new_path}")
                count += 1
    if count == 0:
        print("No matching files found.")


# Duplicates a file with the option to rename both old and new versions
def duplicate_file_or_folder(target, new_name_original, new_name_copy):
    target_path = os.path.join(current_dir, target)
    
    if os.path.isfile(target_path):
        dir_path = os.path.dirname(target_path)
        path_new_original = os.path.join(dir_path, new_name_original)
        path_new_copy = os.path.join(dir_path, new_name_copy)

        try:
            shutil.copy2(target_path, path_new_copy)
            os.rename(target_path, path_new_original)
            print(f"Original renamed: {target_path} → {path_new_original}")
            print(f"Copy created: {path_new_copy}")
        except Exception as e:
            print(f"Error during duplication: {e}")

    elif os.path.isdir(target_path):
        file_list = [
            f for f in os.listdir(target_path)
            if os.path.isfile(os.path.join(target_path, f))
        ]
        if not file_list:
            print("No files to duplicate in folder.")
            return

        for filename in file_list:
            src_path = os.path.join(target_path, filename)
            base, ext = os.path.splitext(filename)
            renamed_original = f"{new_name_original}_{base}{ext}"
            renamed_copy = f"{new_name_copy}_{base}{ext}"

            full_original = os.path.join(target_path, renamed_original)
            full_copy = os.path.join(target_path, renamed_copy)

            try:
                shutil.copy2(src_path, full_copy)
                os.rename(src_path, full_original)
                print(f"{src_path} → {full_original} and {full_copy}")
            except Exception as e:
                print(f"Error duplicating {src_path}: {e}")
    else:
        print(f"Error: '{target_path}' is not a valid file or folder.")

# Within-interface navigation
def change_directory(path):
    global current_dir
    if os.path.isdir(path):
        current_dir = os.path.abspath(path)
        print(f"Working directory changed to: {current_dir}")
    else:
        print(f"Error: '{path}' is not a valid directory.")

def print_help():
    print(f"""
Current working directory: {current_dir}

Available commands:
    cd <folder>                                              Change working directory
    rename <find_str> <replace_str> [--recursive]            Rename files in current directory
    duplicate <file_or_folder> <new_name_original> <copy>    Duplicate file or all files in a folder
    help                                                     Show this help message
    exit / quit                                              Exit the program
    expand <file>                                            Expand multi-year file into one per year

""")

def main():
    global current_dir
    print("File Manager CLI - Type 'help' for instructions")
    while True:
        try:
            user_input = input(">> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not user_input:
            continue

        args = shlex.split(user_input)
        cmd = args[0].lower()

        if cmd in ("exit", "quit"):
            break
        elif cmd == "help":
            print_help()
        elif cmd == "cd":
            if len(args) != 2:
                print("Usage: cd <folder>")
                continue
            change_directory(args[1])
        elif cmd == "rename":
            if len(args) < 3:
                print("Usage: rename <find_str> <replace_str> [--recursive]")
                continue
            find_str = args[1]
            replace_str = args[2]
            recursive = "--recursive" in args[3:]
            find_and_replace_filenames(find_str, replace_str, recursive)
        elif cmd == "duplicate":
            if len(args) != 4:
                print("Usage: duplicate <file_or_folder> <new_name_original> <new_name_copy>")
                continue
            duplicate_file_or_folder(args[1], args[2], args[3])
        elif cmd == "expand":
            if len(args) != 2:
                print("Usage: expand <filename>")
                continue
            expand_file(args[1])

        else:
            print(f"Unknown command: {cmd}. Type 'help' for usage.")

if __name__ == "__main__":
    main()
