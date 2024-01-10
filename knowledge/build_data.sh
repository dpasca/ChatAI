#!/bin/bash

# Usage: ./build_data.sh <source_directory> <output_directory>

src_dir=${1:-src}
output_dir=${2:-_output}

# Call optimize_pdfs.sh with the source and output directories
./optimize_pdfs.sh "$src_dir" "$output_dir"

# Non-PDF files are simply copied over
for file in "$src_dir"/*; do
    if [ ! -f "$file" ]; then
        continue
    fi

    file_name=$(basename "$file")

    # Skip if the file is a PDF
    if [[ $file_name == *.pdf ]]; then
        continue
    fi

    output_path="$output_dir/$file_name"
    cp "$file" "$output_path"

    echo "Copied $file_name"
done

