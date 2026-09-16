# Dansk eller engelsk Gherkin fra en user story

Dette værktøj bruger en lokal Ollama-model til at foreslå Gherkin-scenarier på dansk eller engelsk ud fra en user story og eventuelt en testbasis med acceptkriterier. Dansk er standard. Du kan bruge skrivebordsvinduet på Windows eller køre scriptet i en terminal. Resultatet valideres med `gherkin-official`, før det kan gemmes, men bør stadig gennemgås fagligt.

## Krav og installation

Du skal have Python 3.10 eller nyere med Tkinter (til vinduet), en kørende lokal Ollama-installation og en hentet model. Hent for eksempel standardmodellen med `ollama pull llama3.2`.

I denne mappe er `.venv` allerede oprettet. Hvis du senere skal oprette miljøet igen på Windows, kan du bruge:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-gherkin.txt
```

Hvis `py` ikke findes på din computer, skal du bruge stien til din Python-installation i første kommando. Til terminalbrug på macOS/Linux kan du bruge `python3 -m venv .venv`, aktivere med `source .venv/bin/activate` og installere med `pip install -r requirements-gherkin.txt`.

## Skrivebordsvindue på Windows

Dobbeltklik på `start_gherkin_gui.cmd`. Vinduet bruger som standard `http://localhost:11434` og modellen `llama3.2`.
Klik **Hjælp** i hovedvinduet eller kæde-editoren for vejledning direkte i programmet.

1. Klik på **Kontrollér forbindelse** for at se Ollamas lokale modeller, eller skriv et lokalt modelnavn direkte.
2. Vælg **Dansk** eller **English** under **Scenariesprog**. Valget bestemmer både Gherkin-nøgleord og sproget i navne og trin. En dansk user story kan godt bruges til engelske scenarier.
3. Indsæt en user story eller vælg **Indlæs tekstfil** for en UTF-8-fil. En story må være fri tekst i én eller flere linjer; den behøver ikke følge skabelonen "Som ... vil jeg ... så ...". Beskriv dog adfærd og forventet resultat så konkret som muligt.
4. Indsæt eventuelt acceptkriterier i **Testbasis / acceptkriterier**, eller klik **Indlæs testbasis** for en `.txt`, `.md`, `.pdf` eller `.docx`-fil. Den udtrukne tekst vises i feltet og kan redigeres før generering. Hvis indlæsning mislykkes, bliver eksisterende tekst stående.
5. Vælg **Standard** under **Promptkæde** for det hidtidige forløb, eller vælg en kæde, som passer til scenariesproget. Klik **Redigér kæder** for at oprette en kæde eller kopiere den skrivebeskyttede standard. I editoren kan du navngive, tilføje, slette og flytte trin, redigere både systemprompt og brugerprompt for hvert trin samt redigere reparationsinstruktionen. Gem kæden, før du bruger den.
6. Klik på **Generér scenarier**. **Vis mellemresultater** viser modellens rå svar i et særskilt vindue. Med **Standard** vises første svar og et eventuelt reparationssvar; med en brugerdefineret kæde vises de navngivne trinsvar. De er ikke nødvendigvis gyldig Gherkin og kan ikke gemmes som `.feature` fra dette vindue. Gennemgå det validerede slutresultat i hovedvinduet.
7. Klik på **Gem .feature**. Hvis du ændrer slutresultatet, valideres det igen før gemning.

Serveradresse, model og sprog kan gemmes med **Gem indstillinger** i `gherkin_gui_settings.json`; kædevalget gemmes ikke her. Dine kædedefinitioner ligger lokalt i `gherkin_prompt_chains.json` ved siden af programmet. Hverken user story, testbasis eller genererede svar gemmes i disse JSON-filer. En beskadiget kædefil bevares, og vinduet tilbyder kun Standard med en advarsel, indtil filen rettes. Vinduet accepterer kun lokale serveradresser (`localhost`, `127.0.0.1`, `::1`) og afviser Ollama-modeller mærket `:cloud`. Se også `README-gui.md` for den korte vinduesvejledning.

En brugerdefineret kæde udfører trinnene i rækkefølge med samme valgte lokale model. Første trin kan bruge `{{user_story}}`, `{{test_basis}}` og `{{language}}` i sine promptfelter. Fra trin 2 skal brugerprompten bruge `{{previous_output}}` for at få forrige trins svar; disse pladsholdere kan også bruges i senere trin. Reparationsinstruktionen kan desuden bruge `{{validation_error}}` og `{{invalid_output}}`. Der er ingen forgrening eller særskilt modelvalg pr. trin. Kun det sidste svar valideres som Gherkin; ved valideringsfejl forsøges én redigerbar reparation. Flere trin kræver flere modelkald. Syntaktisk validering erstatter ikke faglig gennemgang.

Testbasis understøtter UTF-8-tekst (`.txt` og `.md`), tekstbaseret PDF (`.pdf`) og Word (`.docx`). Scannede billed-PDF'er læses ikke med OCR, og det ældre Word-format `.doc` understøttes ikke. En fil uden læsbar tekst giver en fejl; du kan i stedet indsætte eller rette tekst direkte i feltet. Den lokale Ollama-model modtager både story og testbasis ved generering, så brug kun materiale, som må behandles af din lokale model.

## Terminalbrug

Indsæt en flerlænjet user story direkte i terminalen:

```powershell
.\.venv\Scripts\python.exe gherkin_story.py
```

Afslut indtastningen med `Ctrl+Z` og Enter på Windows eller `Ctrl+D` på Unix/macOS. Resultatet skrives til standard output; prompt og fejl vises på standard error. På macOS/Linux bruges miljøets `python` i stedet for Windows-stien ovenfor.

Du kan også læse en UTF-8-fil og gemme resultatet:

```powershell
.\.venv\Scripts\python.exe gherkin_story.py --story-file min-story.txt --output min-story.feature
```

Tilføj en separat testbasis og vælg f.eks. engelsk output:

```powershell
.\.venv\Scripts\python.exe gherkin_story.py --story-file min-story.txt --test-basis-file krav.pdf --language en --output scenarier.feature
```

En kæde, som du har gemt for engelsk, kan bruges med `--chain` (navnet skal svare præcist):

```powershell
.\.venv\Scripts\python.exe gherkin_story.py --story-file min-story.txt --test-basis-file krav.pdf --language en --chain "Min kæde" --output scenarier.feature
```

`--test-basis-file` accepterer de samme fire formater som vinduet. Uden testbasis fungerer generering som før. Udtræk fra PDF/Word er kun tekst (ingen OCR), og `.doc` kan ikke indlæses.

Vælg om nødvendigt en anden model eller Ollama-adresse med `--model` og `--ollama-url`. Terminalscriptet forsøger én rettelse, hvis modellens første svar er ugyldigt. Kun et parser-valideret resultat vises eller gemmes, og en eksisterende outputfil bevares ved fejl. Brug en lokal model, hvis user storyen ikke må sendes til en cloud-tjeneste.

Brug `--language en` for engelske scenarier; uden flag bruges dansk (`--language da`):

```powershell
.\.venv\Scripts\python.exe gherkin_story.py --language en --story-file min-story.txt --output min-story-en.feature
```

Dansk output starter med `# language: da` og bruger `Egenskab`, `Scenarie`, `Givet`, `Når`, `Så`. Engelsk output starter med `# language: en` og bruger `Feature`, `Scenario`, `Given`, `When`, `Then`. Indledende blanktegn i modellens svar fjernes kun, når den korrekte sprogmarkør følger; manglende markør og ugyldig Gherkin afvises fortsat. De respektive strukturer valideres før visning og gemning; sproglig og faglig kvalitet skal stadig vurderes af et menneske.

Syntaktisk validering garanterer **ikke**, at scenarierne er domænefagligt korrekte eller dækker alle acceptkriterier. Gennemgå altid forslaget før brug.

## Fejllog

Fejl fra skrivebordsvinduet og terminalscriptet registreres i
`logs\gherkin-errors.log` ved siden af programfilerne. Hver post indeholder
tidspunkt i UTC, handling, fejltype og de relevante kodefiler og linjenumre.
User stories, testbasis, prompts, model-svar og exception-beskeder gemmes ikke
i loggen. Den roterer ved ca. 1 MB og beholder højst tre ældre logfiler.
Den oprindelige fejlbesked vises fortsat i vinduet eller terminalen; ved
uventede fejl henvises du til loggen. Hvis logmappen ikke kan skrives, påvirker
det ikke den oprindelige fejlbehandling. Vær opmærksom på, at den lokale
`pythonscripts`-mappe ligger i OneDrive og derfor kan synkroniseres.

Kør lokale kontroller med `.\.venv\Scripts\python.exe -m unittest discover -q` og se alle terminalflag med `.\.venv\Scripts\python.exe gherkin_story.py --help`.
