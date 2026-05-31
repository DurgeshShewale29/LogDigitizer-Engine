import cv2
import numpy as np
import base64
from app.core.logging import logger

def process_image(image_bytes: bytes) -> str:
    """
    Processes an image strictly in-memory:
    decode -> grayscale -> adaptive binarize -> Hough deskew
    Returns a Base64 encoded string of the processed image.
    """
    try:
        logger.info("Starting image processing pipeline")
        
        # 1. Decode
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Failed to decode image.")
        
        # 2. Grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # 3. Adaptive Binarize
        # block size 11, C=2
        binarized = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        
        # 4. Hough Deskew
        # We invert the binarized image to find lines (white lines on black bg)
        inverted = cv2.bitwise_not(binarized)
        lines = cv2.HoughLinesP(inverted, 1, np.pi / 180, 100, minLineLength=100, maxLineGap=50)
        
        angle = 0.0
        if lines is not None:
            angles = []
            for line in lines:
                x1, y1, x2, y2 = line[0]
                angles.append(np.arctan2(y2 - y1, x2 - x1) * 180.0 / np.pi)
            
            # Median angle of detected lines
            median_angle = np.median(angles)
            
            # If the angle is too large, it might be detecting vertical lines, 
            # we only deskew slightly skewed pages. Let's limit angle to [-45, 45]
            if -45 <= median_angle <= 45:
                angle = median_angle
                logger.info(f"Deskewing image by {angle:.2f} degrees")
        
        # Rotate image if angle is significant
        if abs(angle) > 0.1:
            (h, w) = binarized.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            # Use white background for rotation filling
            processed_img = cv2.warpAffine(binarized, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
        else:
            processed_img = binarized
            
        # Encode back to JPEG
        success, buffer = cv2.imencode('.jpg', processed_img)
        if not success:
            raise ValueError("Failed to encode processed image.")
        
        # Return as Base64 string
        b64_str = base64.b64encode(buffer).decode('utf-8')
        logger.info("Image processing completed successfully")
        return b64_str

    except Exception as e:
        logger.error(f"Error in image pipeline: {e}")
        raise
