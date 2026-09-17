# Dansk og engelsk Gherkin med skrivebordsvindue

Dobbeltklik på `start_gherkin_gui.cmd` på Windows eller `start_gherkin_gui.command` på macOS for at åbne vinduet. Mac-launcheren opretter automatisk `.venv` og installerer afhængigheder første gang. Programmet bruger kun
en lokal Ollama-server (`http://localhost:11434` som standard) og den installerede
Python-model `gherkin-official` til at validere Gherkin.

Klik **Hjælp** i hovedvinduet for en kort vejledning i brug, promptkæder og
fejlfindingsråd. Kæde-editoren har også en **Hjælp**-knap, der åbner direkte
på vejledningen til at kopiere og redigere den skrivebeskyttede Standard-kæde.
Handlingsknapperne har ens bredde, og de højrestillede knapper står på linje;
de nederste knapper i editoren er også synlige ved mindste vinduesstørrelse.

1. Start Ollama, og hent en model, f.eks. `ollama pull llama3.2`.
2. Klik på **Kontrollér forbindelse** for at se lokalt installerede modeller, eller
   skriv et modelnavn direkte i feltet.
3. Vælg **Dansk** eller **English** under **Scenariesprog**. Dansk er standard,
   og valget kan gemmes sammen med serveradresse og model.
4. Indsæt en user story, eller klik **Indlæs tekstfil** for at læse en UTF-8-fil. Fri tekst i én eller flere linjer er tilladt; en bestemt user-story-skabelon er ikke påkrævet.
5. Skriv eventuelt acceptkriterier i **Testbasis / acceptkriterier**, eller klik
   **Indlæs testbasis** for at åbne `.txt`, `.md`, `.pdf` eller `.docx`.
   Udtrukket tekst kan rettes i feltet. Ved indlæsningsfejl bevares tidligere tekst.
6. Vælg **Standard** under **Promptkæde** for det oprindelige forløb, eller vælg
   en gemt kæde for det valgte sprog. Med **Redigér kæder** kan du kopiere den
   skrivebeskyttede standard, oprette og navngive trin, flytte eller slette dem,
   redigere både systemprompt og brugerprompt for hvert trin og ændre den
   fælles reparationsinstruktion. Klik **Gem kæde** i editoren.
7. Klik **Generér scenarier**. **Vis mellemresultater** åbner et særskilt vindue
   med rå model-svar. Med **Standard** vises det første svar og et eventuelt
   reparationssvar; med en brugerdefineret kæde vises de navngivne trinsvar.
   De rå svar kan ikke gemmes som `.feature` derfra. Kun det validerede slutresultat
   vises i hovedfeltet.
8. Gennemgå scenarierne fagligt, og klik **Gem .feature**. Hvis du redigerer
   resultatet, valideres det igen, før filen skrives.

Ved fejl oprettes en teknisk log i `logs\gherkin-errors.log` ved siden af
programfilerne. Den viser tidspunkt (UTC), handling, fejltype og kodefil/-linje,
så du kan finde stedet, hvor fejlen opstod. Loggen indeholder ikke user story,
testbasis, prompts, model-svar eller fejlbeskeder, der kan indeholde disse data.
Filen roterer ved ca. 1 MB og gemmer højst tre ældre filer (`.1`–`.3`).
Den korte fejlbesked vises fortsat i vinduet. Del kun loggen med nogen, du stoler
på; filnavne og kodeplaceringer kan afsløre detaljer om din installation.

Serveradresse, model og sprog kan gemmes med **Gem indstillinger**. Indstillingerne ligger
i `gherkin_gui_settings.json` ved siden af programmet; kædevalget gemmes ikke dér.
Gemte kædedefinitioner ligger lokalt i `gherkin_prompt_chains.json`. Hverken user
stories, testbasis eller modelresultater gemmes i nogen af disse JSON-filer. En
beskadiget kædefil ændres ikke automatisk; du får en advarsel og kun Standard
som valg, indtil den er rettet. Kun lokale adresser
(`localhost`, `127.0.0.1` og `::1`) accepteres.
Modeller med Ollamas `:cloud`-mærkning vises ikke og kan ikke bruges i vinduet.

Tekstfilerne skal være UTF-8. PDF skal indeholde tekst, som kan udtrækkes; der
bruges ikke OCR til scannede billedsider. Ældre Word-filer med `.doc` understøttes
ikke. Du kan altid skrive eller redigere testbasis direkte i feltet. Modellen får
story og testbasis ved generering, men syntaktisk validering er ikke en garanti
for korrekte eller dækkende scenarier.

En kæde kører trin i rækkefølge med samme lokale model uden forgrening eller
modelvalg pr. trin. Promptfelterne kan bruge `{{user_story}}`, `{{test_basis}}`
og `{{language}}`. Fra trin 2 skal brugerprompten indeholde
`{{previous_output}}`; første trin kan ikke bruge den. Den redigerbare
reparationsinstruktion kan også bruge `{{validation_error}}` og
`{{invalid_output}}`. Kun det sidste svar valideres, og ved fejl får modellen
ét reparationsforsøg. Mellemresultater er uvaliderede, og flere trin tager
mere modeltid.

Hvis `.venv` mangler, opret et Python-miljø i denne mappe og installer afhængighederne.
På Windows:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-gherkin.txt
```

På macOS/Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-gherkin.txt
```

Python skal være installeret med Tkinter. Hvis `py` ikke er tilgængelig, kan du
bruge stien til din lokale Python-installation i første kommando. Vinduet kræver
en kørende Ollama-server og en hentet lokal model, men ingen cloud-tjeneste.

Terminaleksempel med testbasis og engelske scenarier:

```powershell
.\.venv\Scripts\python.exe gherkin_story.py --story-file min-story.txt --test-basis-file krav.pdf --language en --chain "Min kæde" --output scenarier.feature
```

På macOS/Linux erstattes `.venv\\Scripts\\python.exe` i eksemplerne ovenfor med
`.venv/bin/python`.

Kæden i eksemplet skal først være gemt for engelsk. Uden `--chain` bruges
standardforløbet. Kør test med `.\.venv\Scripts\python.exe -m unittest discover -q`
og se terminalflag med `.\.venv\Scripts\python.exe gherkin_story.py --help`.
