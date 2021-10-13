import random

def execute(mood):
    if mood == "happy":
        advice = random.choice(["Feliz 1", 
                                "Feliz 2", 
                                "Feliz 3"])

    elif mood == "sad":
        advice = random.choice(["Triste 1",
                                "Triste 2", 
                                "Triste 3"])

    else:
        advice = random.choice(["Enojado 1", 
                                "Enojado 2", 
                                "Enojado 3"])

    return f"say '{advice}'"