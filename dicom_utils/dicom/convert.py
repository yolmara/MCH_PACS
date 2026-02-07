from pathlib import Path
import pydicom
import numpy as np
from PIL import Image
import os

def dicom_to_jpeg(dcm, output_dir, instance_uid):
    #directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Convert pixel data
    pixel_array = dcm.pixel_array.astype(float)
    minv = pixel_array.min()
    maxv = pixel_array.max()
    if maxv == minv:
        scaled = np.zeros_like(pixel_array, dtype=np.uint8)
    else:
        scaled = 255 * (pixel_array - minv) / (maxv - minv)
        scaled = scaled.astype(np.uint8)
