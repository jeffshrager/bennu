import sys
import re
from typing import List, Tuple, Set

def logcat():
    """
    Reads multiple log files, extracts unique sensor records, sorts them chronologically,
    and prints the result to standard output.
    """
    if len(sys.argv) < 2:
        # Check if any files were passed as arguments
        print(f"Usage: python {sys.argv[0]} <log_file_1> [<log_file_2> ...]", file=sys.stderr)
        sys.exit(1)

    # List to store (sort_key, full_log_line) tuples
    all_records: List[Tuple[str, str]] = []
    # Set to track and prevent duplicate lines
    seen_lines: Set[str] = set()

    # Regex to identify a sensor log line and capture the primary timestamp (the sort key)
    # The sort key is the timestamp at the very start of the log line (e.g., 2025-12-06T17:14:37-0800)
    # This pattern ensures we only process lines containing the "Sensors:" payload.
    sensor_line_pattern = re.compile(
        r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+\-]\d{4}).*\[INFO\]\s+Sensors:\s+.*"
    )

    # Process all files provided as command-line arguments
    for filename in sys.argv[1:]:
        try:
            with open(filename, 'r') as f:
                print(f"Processing {filename}...", file=sys.stderr)
                
                for line in f:
                    line = line.strip()
                    match = sensor_line_pattern.match(line)

                    if match:
                        # Use the full line for de-duplication
                        if line not in seen_lines:
                            # Extract the primary timestamp (Group 1) for sorting
                            sort_key = match.group(1) 
                            
                            # Add to set to mark as seen
                            seen_lines.add(line)
                            
                            # Store the sort key and the full line
                            all_records.append((sort_key, line))
                            
        except FileNotFoundError:
            print(f"Error: File not found: {filename}. Skipping.", file=sys.stderr)
        except Exception as e:
            print(f"An error occurred while reading {filename}: {e}. Skipping.", file=sys.stderr)

    # --- Sorting and Output ---
    
    # Sort the records based on the first element of the tuple (the timestamp).
    # Python's string sorting works correctly for ISO 8601 timestamps.
    all_records.sort(key=lambda x: x[0])
    
    print(f"Total unique sensor records found: {len(all_records)}", file=sys.stderr)

    # Print the full log line (the second element of the tuple)
    for _, line in all_records:
        print(line)

if __name__ == "__main__":
    logcat()
    
