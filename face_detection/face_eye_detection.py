import cv2
from time import sleep

cap = cv2.VideoCapture(0) # Open camera
face_cascade = cv2.CascadeClassifier('haarcascade_frontalface_default.xml') # Load Haar cascade
eye_cascade = cv2.CascadeClassifier('haarcascade_eye.xml')

while True:
    ret, frame = cap.read()
    if not ret:
        print("Cannot read from camera.")
        break

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) # Convert to grayscale for detection
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5) # Detect faces

    if len(faces) > 0:
        for (x, y, w, h) in faces:
            print("Face at:", (x, y))
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            
            # Region of interest for eyes (inside the face)
            roi_gray = gray[y:y + h, x:x + w]
            roi_color = frame[y:y + h, x:x + w]
            
            # Detect eyes within the face region
            eyes = eye_cascade.detectMultiScale(
                roi_gray,
                scaleFactor=1.1,
                minNeighbors=10,
                minSize=(20, 20)
            )
            
            eye_count = 0
            for (ex, ey, ew, eh) in eyes:
                # Only consider eyes in the upper half of the face
                if ey + eh < h // 2:
                    print("  Eye at:", (x + ex, y + ey))
                    cv2.rectangle(roi_color, (ex, ey), (ex + ew, ey + eh), (255, 0, 0), 2)
                    eye_count += 1
                
                if eye_count >= 2:
                    break
    else:
        print("No faces detected.")

    # Show the result
    cv2.imshow('Face and Eye Detection', frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

    sleep(0.1) # Wait for 100 ms

# Release camera and close all windows
cap.release()
cv2.destroyAllWindows()