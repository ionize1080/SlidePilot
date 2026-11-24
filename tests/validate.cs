using System;
using System.IO;
using System.Linq;
using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Validation;

class Validate {
    static int Check(string file) {
        int count = 0;
        var validator = new OpenXmlValidator(FileFormatVersions.Office2010);
        using (var deck = PresentationDocument.Open(file, false)) {
            foreach (var error in validator.Validate(deck).Take(40)) {
                Console.WriteLine(Path.GetFileName(file) + " " + error.Description);
                count++;
            }
            var presentation = deck.PresentationPart;
            var notes = presentation.NotesMasterPart;
            if (notes != null && notes.ThemePart != null && presentation.SlideMasterParts.Any(
                    master => master.ThemePart != null && master.ThemePart.Uri == notes.ThemePart.Uri)) {
                Console.WriteLine("PowerPoint requires a separate theme part for the notes master.");
                count++;
            }
            foreach (var slide in presentation.SlideParts) foreach (var chart in slide.ChartParts) {
                var embedded = chart.EmbeddedPackagePart;
                if (embedded == null) {
                    Console.WriteLine(chart.Uri + " has no embedded workbook.");
                    count++;
                    continue;
                }
                using (var stream = embedded.GetStream())
                using (var book = SpreadsheetDocument.Open(stream, false))
                    foreach (var error in validator.Validate(book).Take(40)) {
                        Console.WriteLine(embedded.Uri + " " + error.Description);
                        count++;
                    }
            }
        }
        return count;
    }

    static int Main(string[] filenames) {
        if (filenames.Length == 0) return 2;
        int count = 0;
        foreach (var file in filenames) try { count += Check(file); }
        catch (Exception error) { Console.WriteLine(Path.GetFileName(file) + " " + error.Message); count++; }
        Console.WriteLine("Office 2010 package validation errors: " + count);
        return count == 0 ? 0 : 1;
    }
}
