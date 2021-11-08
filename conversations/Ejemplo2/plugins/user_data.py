# Comprobar si un usuario es nuevo o no

import pandas as pd

texto = pd.read_csv("user_data.csv")

if texto.iloc[0,0] == "nuevo":
	texto.iloc[0,0] = "conocido"
	return "solve usuario_nuevo"
else:
	return "solve bienvenida"