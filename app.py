from airac_db import AiracRepository

# 3. O Teste de Bancada
if __name__ == "__main__":

    banco_nav = AiracRepository(ciclo="2606")

    try:
        resp = banco_nav.buscar_aerodromo("SBRJ")
        print(resp)
    except ValueError as e:
        print(e)