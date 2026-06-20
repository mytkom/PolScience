package org.example;

import java.io.FileWriter;
import java.io.IOException;
import java.io.Writer;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVPrinter;

public class CsvWriterService {

    public static void writeResponseResultsToCsv(ResponseResults responseResults, String filePath)
    {
        try (
            Writer writer = new FileWriter(filePath);
            CSVPrinter csvPrinter = new CSVPrinter(writer, CSVFormat.DEFAULT.builder()
                .setHeader(
                    "id", "name", "objectType",
                    "country", "regon", "countryCd", "pib", "institutionUuid",
                    "lNumber", "managerName", "eMail", "nip", "www",
                    "iKindName", "postalCd", "bNumber", "phone", "iStartDT",
                    "dataSource", "status", "statusCode", "city", "siTypeName",
                    "street", "voivodeship", "lastRefresh", "krs",
                    "institutionUid", "siTypeCd", "uTypeCd", "voivodeshipCode",
                    "addresses", "supervisingInstitutions", "statuses", "types", "names"
                )
                .build())
        ) {
            if (responseResults == null || responseResults.getResults() == null) {
                return;
            }

            for (InstitutionResponse institution : responseResults.getResults()) {
                InstitutionObject obj = institution.getObject();

                csvPrinter.printRecord(
                    institution.getId(),
                    institution.getName(),
                    institution.getObjectType(),

                    obj != null ? obj.getCountry() : null,
                    obj != null ? obj.getRegon() : null,
                    obj != null ? obj.getCountryCd() : null,
                    obj != null ? obj.getPib() : null,
                    obj != null ? obj.getInstitutionUuid() : null,
                    obj != null ? obj.getLNumber() : null,
                    obj != null ? obj.getManagerName() : null,
                    obj != null ? obj.getEMail() : null,
                    obj != null ? obj.getNip() : null,
                    obj != null ? obj.getWww() : null,
                    obj != null ? obj.getIKindName() : null,
                    obj != null ? obj.getPostalCd() : null,
                    obj != null ? obj.getBNumber() : null,
                    obj != null ? obj.getPhone() : null,
                    obj != null ? obj.getIStartDT() : null,
                    obj != null ? obj.getDataSource() : null,
                    obj != null ? obj.getStatus() : null,
                    obj != null ? obj.getStatusCode() : null,
                    obj != null ? obj.getCity() : null,
                    obj != null ? obj.getSiTypeName() : null,
                    obj != null ? obj.getStreet() : null,
                    obj != null ? obj.getVoivodeship() : null,
                    obj != null ? obj.getLastRefresh() : null,
                    obj != null ? obj.getKrs() : null,
                    obj != null ? obj.getInstitutionUid() : null,
                    obj != null ? obj.getSiTypeCd() : null,
                    obj != null ? obj.getUTypeCd() : null,
                    obj != null ? obj.getVoivodeshipCode() : null,

                    obj != null ? joinAddresses(obj.getAddresses()) : null,
                    obj != null ? joinSupervisingInstitutions(obj.getSupervisingInstitutions()) : null,
                    obj != null ? joinStatuses(obj.getStatuses()) : null,
                    obj != null ? joinTypes(obj.getTypes()) : null,
                    obj != null ? joinNames(obj.getNames()) : null
                );
            }

            csvPrinter.flush();
        }
        catch (IOException e)
        {
            throw new RuntimeException(e);
        }
    }

    public static void writeUniYearCount(final Map<String, Map<String, Integer>> uniByYearAndCount,
                                         final Map<String, String> uniNameAndId,
                                         final String filePath
                                         ) {
        try (
            Writer writer = new FileWriter(filePath);
            CSVPrinter csvPrinter = new CSVPrinter(writer, CSVFormat.DEFAULT.builder()
                .setHeader("id", "name", "2019", "2020", "2021", "2022", "2023", "2024")
                .build())
        )
        {
            if (uniByYearAndCount == null) {
                return;
            }
            uniByYearAndCount.forEach((uniName, value) -> {
                final String uniId = uniNameAndId.get(uniName);
                Integer year2019Count = value != null ? value.get("2019") : null;
                Integer year2020Count = value != null ? value.get("2020") : null;
                Integer year2021Count = value != null ? value.get("2021") : null;
                Integer year2022Count = value != null ? value.get("2022") : null;
                Integer year2023Count = value != null ? value.get("2023") : null;
                Integer year2024Count = value != null ? value.get("2024") : null;
                try
                {
                    csvPrinter.printRecord(
                        uniId,
                        uniName,
                        year2019Count,
                        year2020Count,
                        year2021Count,
                        year2022Count,
                        year2023Count,
                        year2024Count
                    );
                }
                catch (IOException e)
                {
                    throw new RuntimeException(e);
                }
            });

            csvPrinter.flush();
        }
        catch (IOException e)
        {
            throw new RuntimeException(e);
        }
    }

    private static String joinAddresses(List<Address> addresses) {
        if (addresses == null || addresses.isEmpty()) {
            return "";
        }

        return addresses.stream()
            .map(a -> String.join(" | ",
                nullSafe(a.getCountry()),
                nullSafe(a.getVoivodeship()),
                nullSafe(a.getCity()),
                nullSafe(a.getPostalCd()),
                nullSafe(a.getStreet()),
                nullSafe(a.getBNumber()),
                nullSafe(a.getLNumber()),
                nullSafe(a.getDateFrom())
            ))
            .collect(Collectors.joining(" ; "));
    }

    private static String joinSupervisingInstitutions(List<SupervisingInstitution> institutions) {
        if (institutions == null || institutions.isEmpty()) {
            return "";
        }

        return institutions.stream()
            .map(s -> String.join(" | ",
                nullSafe(s.getSupervisingInstitutionID()),
                nullSafe(s.getSupervisingInstitutionName()),
                nullSafe(s.getDateFrom())
            ))
            .collect(Collectors.joining(" ; "));
    }

    private static String joinStatuses(List<Status> statuses) {
        if (statuses == null || statuses.isEmpty()) {
            return "";
        }

        return statuses.stream()
            .map(s -> String.join(" | ",
                nullSafe(s.getStatusName()),
                nullSafe(s.getDateFrom())
            ))
            .collect(Collectors.joining(" ; "));
    }

    private static String joinTypes(List<Type> types) {
        if (types == null || types.isEmpty()) {
            return "";
        }

        return types.stream()
            .map(t -> String.join(" | ",
                nullSafe(t.getTypeName()),
                nullSafe(t.getDateFrom())
            ))
            .collect(Collectors.joining(" ; "));
    }

    private static String joinNames(List<NameRecord> names) {
        if (names == null || names.isEmpty()) {
            return "";
        }

        return names.stream()
            .map(n -> String.join(" | ",
                nullSafe(n.getName()),
                nullSafe(n.getDateFrom())
            ))
            .collect(Collectors.joining(" ; "));
    }

    private static String nullSafe(String value) {
        return value == null ? "" : value;
    }

}
