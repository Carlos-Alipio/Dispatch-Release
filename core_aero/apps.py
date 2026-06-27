from core_aero.airac_repo import AiracRepository

if __name__ == "__main__":

    banco_nav = AiracRepository(ciclo="2606")

    try:
        resp = banco_nav.buscar_aerodromo("SBRJ")
        print(resp)
    except ValueError as e:
        print(e)
