# Como foi feita a versão 1.0

Registro de como o Capture Pro 1.0 foi construído em 15/10/2026, para servir de
referência nas próximas versões.

## 1. Ponto de partida

- **Especificação completa:** [`especificacao-original.txt`](especificacao-original.txt)
  (objetivo, dispositivos, interface, recorte, ajustes, formatos, testes e regras de entrega).
- **Modelo visual:** um protótipo de interface em português (tema escuro, prévia ao vivo,
  "Área de captura ajustável", botões *Definir área / Tela inteira / Salvar imagem*,
  ajustes de brilho/contraste/saturação/nitidez, pasta `C:\Capturas`).
- **Uso principal:** capturar imagens estáticas de equipamentos de endoscopia ligados ao PC
  por placa de captura, com fidelidade de imagem e recorte permanente.

## 2. Decisão de tecnologia

A especificação preferia **C# / .NET 8 / WPF**. O ambiente de construção (um servidor Linux
na nuvem) não conseguia acessar os servidores da Microsoft (SDK .NET e NuGet bloqueados).
A alternativa escolhida mantém os mesmos requisitos e tecnologias de captura do Windows:

| Pedido | Usado na 1.0 | Motivo |
|---|---|---|
| C# / .NET 8 | Python 3.12 embutido + lançador nativo em C (`CapturePro.exe`) | Disponível offline; o usuário final não instala nada |
| WPF | Qt 6 (PySide6) Widgets | Interface nativa, moderna, compilada de Linux para Windows |
| DirectShow / Media Foundation | OpenCV (`CAP_DSHOW` e `CAP_MSMF`) + comtypes/pygrabber | Mesmas APIs do Windows; consulta direta aos modos e ao crossbar |
| OpenCV | OpenCV 4.14 | Igual ao pedido |
| Instalador Windows | NSIS 3 em português | Gera `.exe` de instalação a partir do Linux |

Versões fixadas em [`build/requirements-windows.txt`](../build/requirements-windows.txt).
Python para Windows: `python-build-standalone` 3.12.8 (tag 20250115).

## 3. Etapas seguidas

1. **Estrutura modular** (`src/capturepro/`): captura, processamento, salvamento,
   configurações e interface em módulos separados.
2. **Descoberta de dispositivos** (`devices.py`, `dshow.py`): nomes das placas pelo
   DirectShow; modos *reais* lidos de `IAMStreamConfig` (VIDEOINFOHEADER e
   VIDEOINFOHEADER2, com FOURCC); entradas físicas pelo `IAMCrossbar`
   (HDMI/SDI, RCA, S-Video, componente…). Quando o driver não informa os modos, o programa
   testa resoluções comuns e guarda só as aceitas. Funciona também em Windows "N"
   (sem Wmvcore.dll).
3. **Prévia ao vivo** (`capture.py`): thread dedicada; a interface só recebe uma imagem
   reduzida do tamanho da tela; detecta "sem sinal" (falta de quadros ou imagem preta)
   e reconecta sozinha quando a placa volta.
4. **Área de captura** (`ui/video_view.py`): moldura guardada em coordenadas normalizadas
   (0–1) da imagem, portanto independente do tamanho da janela; convertida para pixels
   reais do vídeo só ao salvar; mover, redimensionar por 4 cantos e 4 bordas, desenhar
   nova; escurecimento externo; nunca aparece na foto; memorizada por dispositivo.
5. **Ajustes e salvamento** (`processing.py`, `storage.py`): ajustes lineares
   (LUT brilho/contraste, mistura com cinza para saturação, *unsharp mask* para nitidez);
   em zero a foto é bit a bit igual ao quadro. Pipeline: recorte → ajustes →
   redimensionamento sem deformar (aviso de interpolação). PNG/JPEG/BMP; nomes
   `PREFIXO_AAAA-MM-DD_NNN`; criação exclusiva do arquivo (nunca sobrescreve, nunca deixa
   arquivo parcial); gravação fora da thread da interface.
6. **Interface e atalhos** (`ui/main_window.py`, `ui/theme.py`): F8 salvar, F11 tela cheia,
   ESC sair; miniatura da última foto; contador; abrir pasta; iniciar com o Windows
   (registro `HKCU\...\Run`, desligado por padrão); instância única; log em
   `%APPDATA%\CapturePro`.
7. **Compilação**: lançador C compilado com MinGW (ícone, manifesto, versão);
   `build/assemble.py` monta a pasta do programa, remove partes do Qt não usadas e
   **verifica todas as DLLs pelos cabeçalhos PE**.
8. **Instalador**: NSIS, dividido em duas partes (limite de 30 MB de envio de arquivos no chat):
   `CapturePro-Setup-1.0.0.exe` (programa) chama `CapturePro-Setup-1.0.0-parte2.exe`
   (OpenCV) automaticamente; avisa se faltar a parte 2.
9. **Testes** (ver abaixo).

Tudo é reproduzível com `./build/build.sh` (Ubuntu 24.04 + `nsis` + `gcc-mingw-w64-x86-64`).

## 4. Testes e resultados

- **35 testes automatizados (pytest) — todos aprovados**, com fonte de vídeo simulada
  (`CAPTUREPRO_TEST_SOURCE=1`): recorte em pixels reais, moldura com mouse, recorte
  independente da janela, PNG/BMP sem perda, JPEG, ajustes e restauração, numeração sem
  sobrescrever, pastas com acentos, F8/F11/ESC, tela cheia, troca de resolução/fps/entrada,
  sem sinal, reconexão, persistência ao reabrir, configuração corrompida, sem dispositivos,
  leitura de formatos DirectShow.
- **Wine 9 (simulação do Windows em Linux):** instalação em duas partes, arquivos,
  atalhos, entrada em *Aplicativos*, aviso de parte 2 ausente, desinstalação, lançador
  iniciando o Python isolado, mensagem de erro de inicialização, opção *Iniciar com o
  Windows*, falha do DirectShow tratada sem fechar o programa.

**Teste de campo em Windows real (realizado e informado pelo autor, Dr. Celso Matos
Junior, em 15/10/2026):** testado com placa de captura **USB 3.0 com entrada HDMI**
para captura de **ultrassonografia em equipamento de última geração V7** —
**100% funcional**.

**Ainda não testado:** outros tipos de placa (USB 2.0, PCI/PCIe, DirectShow antigas),
entradas RCA/S-Video, troca de entrada pelo crossbar e Media Foundation.

## 5. Pendências para a próxima versão

- Em caso de problema com outras placas, enviar `%APPDATA%\CapturePro\capturepro.log`.
- Assinatura digital do instalador (evita o aviso do SmartScreen).
- Opcional: reescrever em C#/.NET 8/WPF se o ambiente tiver acesso ao SDK da Microsoft.
