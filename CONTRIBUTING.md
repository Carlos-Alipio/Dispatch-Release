# Guia de Contribuição

## Ambiente

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # preencha os valores
python manage.py runserver
```

O banco AIRAC (`core_aero/data/airac/airac_atual.s3db`, ~173 MB) fica fora do git.
Sem ele, a API de dados responde 503, mas a UI e os testes de domínio funcionam.

## Testes

```bash
pytest
```

Os testes de integração do repositório são pulados automaticamente quando o
banco AIRAC não está presente (ex.: no CI).

## Mensagens de commit

O projeto segue [Conventional Commits](https://www.conventionalcommits.org/pt-br/):
`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`, `style:`.

Ative o template local (uma vez por clone):

```bash
git config commit.template .gitmessage
```

Nunca commite mensagens vazias ou "." — o histórico é documentação.

## Segredos

Nunca commite chaves ou senhas. Tudo que é segredo vai no `.env` (ignorado
pelo git); o `.env.example` documenta as variáveis necessárias.
