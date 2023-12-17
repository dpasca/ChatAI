from PIL import Image, ImageDraw, ImageOps

# Open the image file
img = Image.open('static/assistant_avatar.jpg').convert("RGBA")

# Calculate dimensions for cropping
cropCoe = 0.02
width, height = img.size
left   = width  * cropCoe
top    = height * cropCoe
right  = width  * (1 - cropCoe)
bottom = height * (1 - cropCoe)

# Crop the image
img = img.crop((left, top, right, bottom))

# Create a white circle on a black background as a mask
mask = Image.new('L', img.size, 0)
draw = ImageDraw.Draw(mask)
draw.ellipse((0, 0) + img.size, fill=255)

# Apply the mask to the image
result = ImageOps.fit(img, mask.size, centering=(0.5, 0.5))
result.putalpha(mask)

# Resize the image
result = result.resize((32, 32), Image.LANCZOS)

# Save the image
result.save('static/favicon.ico')