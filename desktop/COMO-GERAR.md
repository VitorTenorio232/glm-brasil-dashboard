# Flash View para Windows

O aplicativo roda o **mesmo `app.py` do site** num servidor Streamlit local e o
mostra numa janela nativa (Microsoft Edge WebView2). Por isso fica idêntico ao
site: mesmas abas, mapas, gráficos e downloads. Qualquer mudança no site entra
no app na próxima compilação.

## Gerar o .exe pelo GitHub (recomendado)

1. Envie a pasta `desktop/` e o arquivo `.github/workflows/build-windows.yml` ao repositório.
2. No GitHub: **Actions → Build Flash View (Windows) → Run workflow**.
3. Em ~10–15 min, baixe `FlashView-Windows-x64` em **Artifacts** no fim da página da execução.
4. Opcional: criar uma tag (`git tag v1.0.0 && git push --tags`) publica o ZIP em **Releases**.

## Gerar no seu próprio Windows

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r desktop\requirements-desktop.txt
pyinstaller --noconfirm desktop\FlashView.spec
```
O resultado fica em `dist\FlashView\FlashView.exe` (leve a pasta inteira).

## Testar sem compilar

```bat
python desktop\flashview_desktop.py
```

## Segredos

O token do Hugging Face **não** é embutido no executável (qualquer pessoa
conseguiria extraí-lo). O app procura `secrets.toml` ao lado do `.exe`,
em `.streamlit\secrets.toml` ao lado do `.exe` ou em `%APPDATA%\FlashView\`.
Veja `secrets.toml.exemplo`.

Log de erros: `%LOCALAPPDATA%\FlashView\flashview.log`.
