import cv2

cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)   # Windows
# cap = cv2.VideoCapture(0)                # 其他情况下可试这个

print("isOpened:", cap.isOpened())

ret, frame = cap.read()
print("ret:", ret)

if ret and frame is not None:
    print("shape:", frame.shape)
    print("mean pixel:", frame.mean())
    cv2.imshow("test", frame)
    cv2.waitKey(0)

cap.release()
cv2.destroyAllWindows()