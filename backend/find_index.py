import cv2

for i in range(6):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
    ok, frame = cap.read()

    if ok and frame is not None and frame.size > 0:
        max_px = int(frame.max())
        print(f"index={i}  ok={ok}  max_px={max_px}  shape={frame.shape}  — press ENTER to see next")

        # Annotate the frame
        label = f"Camera index {i}  |  {frame.shape[1]}x{frame.shape[0]}  |  press ENTER for next"
        cv2.putText(frame, label, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)
        cv2.imshow(f"Camera index {i}", frame)

        # Wait until ENTER (key code 13) is pressed — any other key is ignored
        while True:
            key = cv2.waitKey(0) & 0xFF
            if key == 13:   # Enter
                break

        cv2.destroyAllWindows()
    else:
        print(f"index={i}  ok={ok}  — no signal / not available")

    cap.release()

print("Done.")