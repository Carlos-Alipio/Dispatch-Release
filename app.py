from core_aero.airac_repository import AiracRepository

# 3. O Teste de Bancada
if __name__ == "__main__":

    banco_nav = AiracRepository(ciclo="2606")

    try:
        resp = banco_nav.buscar_aerodromo("SBRJ")
        resp2 = banco_nav.buscar_pistas("SBRJ")
        print(resp)
        print(resp2)
    except ValueError as e:
        print(e)
