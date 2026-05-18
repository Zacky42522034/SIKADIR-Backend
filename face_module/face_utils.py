import math

def face_confidence(face_distance, face_match_threshold=0.6):
    range_val = 1.0 - face_match_threshold
    linear_val = (1.0 - face_distance) / (range_val * 2.0)

    if face_distance > face_match_threshold:
        return str(round(linear_val * 100, 2)) + "%"
    else:
        value = (
            linear_val + ((1.0 - linear_val) * math.pow((linear_val - 0.5) * 2, 0.2))
        ) * 100
        return str(round(value, 2)) + "%"