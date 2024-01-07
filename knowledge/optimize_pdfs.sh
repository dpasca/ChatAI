#!/bin/bash

# Usage: ./optimize_pdfs.sh <source_directory> <output_directory> <quality>
# Quality can be a value between 0 and 100, where lower means more compression

src_dir=$1
output_dir=$2
quality=${3:-15}  # Default quality is 15 if not provided

# Check if source directory exists
if [ ! -d "$src_dir" ]; then
    echo "Source directory does not exist."
    exit 1
fi

# Create output directory if it doesn't exist
mkdir -p "$output_dir"

# Process each PDF in the source directory
for pdf_file in "$src_dir"/*.pdf; do
    file_name=$(basename "$pdf_file")
    output_path="$output_dir/$file_name"

    # Ghostscript command for heavy image compression and font substitution
    gs -sDEVICE=pdfwrite -dCompatibilityLevel=1.4 \
       -dPDFSETTINGS=/screen \
       -dEmbedAllFonts=false -dSubsetFonts=true \
       -dDownsampleColorImages=true -dColorImageDownsampleType=/Bicubic \
       -dColorImageResolution=$quality \
       -dDownsampleGrayImages=true -dGrayImageDownsampleType=/Bicubic \
       -dGrayImageResolution=$quality \
       -dDownsampleMonoImages=true -dMonoImageDownsampleType=/Subsample \
       -dMonoImageResolution=$quality \
       -dNOPAUSE -dBATCH -dQUIET \
       -sOutputFile="$output_path" "$pdf_file"

    echo "Processed $file_name"
done

# Non-PDF files are simply copied over
for file in "$src_dir"/*; do
    if [ ! -f "$file" ]; then
        continue
    fi

    file_name=$(basename "$file")
    output_path="$output_dir/$file_name"

    # Skip if the file is a PDF
    if [[ $file_name == *.pdf ]]; then
        echo "Skipping $file_name"
        continue
    fi

    cp "$file" "$output_path"

    echo "Copied $file_name"
done

echo "All files processed."
