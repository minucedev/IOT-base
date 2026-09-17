import cv2
from time import sleep

cap = cv2.VideoCapture(0) # Open camera
face_cascade = cv2.CascadeClassifier('haarcascade_frontalface_default.xml') # Load haar cascade

while True:
    ret, frame = cap.read() # Read frame from camera
    if not ret:
        print("Cannot read camera.")
        break
        
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) # Convert image to grayscale for processing
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
    
    if len(faces) > 0:
        for (x, y, w, h) in faces:
            print("Face at:", (x, y))
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
    else:
        print("No faces detected.")
        
    cv2.imshow('Face Detection', frame)
    
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break
        
    sleep(0.1) # Wait for 100ms
    
# Release camera and close window
cap.release()
cv2.destroyAllWindows()