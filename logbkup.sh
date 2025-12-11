#!/bin/bash

# --- Configuration ---
REMOTE_SOURCE="rome:/home/bennu/software/bennu/logbkup"
LOCAL_DEST_DIR="./logbkup"
# The remote host is "rome" and the remote directory is "/home/sourcedir"

# --- 1. Secure Copy Files ---
echo "1. Fetching files from ${REMOTE_SOURCE} to ${LOCAL_DEST_DIR}..."

# -p: Preserves modification times (mtime) and access times (atime) from the original file
# -r: Recursive, gets the whole dir, and anything under it.
scp -pr "${REMOTE_SOURCE}/" "${LOCAL_DEST_DIR}" || { echo "Error: SCP command failed. Check connection/credentials."; exit 1; }

echo "SCP completed successfully. Files are in ${LOCAL_DEST_DIR}."

# --- 2. Rename Copied Files ---
echo "2. Renaming files to include timestamp and random component (using current time as fallback)..."

# Find all files in the current directory (maxdepth 1) and process them.
find "${LOCAL_DEST_DIR}" -maxdepth 1 -type f -print0 | while IFS= read -r -d $'\0' filepath; do
    
    original_filename=$(basename "$filepath")
    
    # --- A. Attempt to get the preserved modification time (mtime) ---
    # We suppress stat's error output (2>/dev/null) and capture the result.
    preserved_timestamp=$(stat -c "%Y%m%d%H%M" "$filepath" 2>/dev/null)
    STAT_EXIT_CODE=$?
    
    # --- B. Check for stat success and apply fallback logic ---
    if [ $STAT_EXIT_CODE -eq 0 ]; then
        # Success: Use the preserved mtime
        final_timestamp="$preserved_timestamp"
    else
        # Failure: Use the current system time as fallback
        echo "Warning: Could not get preserved timestamp (mtime) for ${original_filename}. Using current time as fallback."
        
        # Get the current time in the required format
        final_timestamp=$(date +%Y%m%d%H%M)
    fi
    
    # --- C. Generate random suffix and perform rename ---
    
    # Generate a 4-digit zero-padded random number
    random_suffix=$(od -An -N4 -i /dev/urandom | awk '{printf "%04d", $1 % 10000}')

    # Construct the new filename: YYYYMMDDHHMM####_originalfilename
    new_filename="${final_timestamp}${random_suffix}_${original_filename}"

    # Perform the rename
    if [ "$original_filename" != "$new_filename" ]; then
        mv -v "$filepath" "${LOCAL_DEST_DIR}/${new_filename}"
    fi

done

echo "Fetch and renaming process completed."
