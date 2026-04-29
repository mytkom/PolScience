package org.example;

import static org.example.CsvWriterService.writeResponseResultsToCsv;
import static org.example.CsvWriterService.writeUniYearCount;
import static org.example.Utility.GENERAL_UNI_INFO_API;
import static org.example.Utility.INSTITUTION_SPECIFIC_API;
import static org.example.Utility.sentHttpRequest;
import static org.example.Utility.showChosenOptionDetails;
import static org.example.Utility.validateInput;

import java.io.File;
import java.io.IOException;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Scanner;
import java.util.Set;
import java.util.stream.Collectors;
import java.util.stream.StreamSupport;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

public class Main
{
    public static final ObjectMapper objectMapper = new ObjectMapper();
    public static final int INITIAL_PAGING_SIZE = 1;
    public static final int INITIAL_PAGING_OFFSET = 0;

    public static void main(String[] args)
        throws IOException
    {
        final HttpBody httpBody = HttpBody.builder()
            .offset(INITIAL_PAGING_OFFSET)
            .size(INITIAL_PAGING_SIZE)
            .objectTypes(List.of("REPORTS_INSTITUTION"))
            .sorting(Map.of("fieldName", "name", "sortOrder", "ASC")).build();

        final String messageMultipleAnswers = "Here are available %1$s, if you want to filter choose the %1$s numbers\n "
            + "writing numbers with coma like x,y,z  or write None\n";
        final String messageOneOption = "Here are available %1$s, please choose one of available option's number code or write None\n";
        final String responseVoivodshipTypes = GetData.getVoivodships();
        final String responseInstitutionTypes = GetData.getInstitutionTypes();
        final String universityStatuses = GetData.getUniversityStatuses();
        final String responseSupervisingAuthorities = GetData.getSupervisingAuthorities();
        final String responseUniTypes = GetData.getUniversityTypes();
        final String scientificInstitutionTypes = GetData.getScientificInstitutionTypes();

        final Scanner sc = new Scanner(System.in);
        final String firstGreetingMessage = """
            Hello! Before extracting university data, you will need to set up few
            options:
                1) Provinces
                2) Type Of Institutions
                3) Status of Institution
                4) Supervising authority
                5) Type of university
                6) Type of scientific institution
            Please choose each menu item number <x> and choose options from there for filter or you will have no filter button too. After sixth option two csv files will be created
            according to your extraction filers!
            """;
        System.out.print(firstGreetingMessage);
        validateInput(sc, 1);
        List<WrapperHttpResp> jsonMappedHttpVoivodshipResponse = objectMapper.readValue(
            responseVoivodshipTypes,
            new TypeReference<>() {}
        );
        showChosenOptionDetails(jsonMappedHttpVoivodshipResponse,
            sc, httpBody, "province", "voivodeshipCodes", messageMultipleAnswers);
        System.out.println("Now please choose the <2> Type of Institution Option");
        validateInput(sc, 2);
        List<WrapperHttpResp> jsonMappedHttpInstitutionTypes = objectMapper.readValue(
            responseInstitutionTypes,
            new TypeReference<>() {}
        );
        Set<String> instCodes  = showChosenOptionDetails(jsonMappedHttpInstitutionTypes,
            sc, httpBody, "Type of Institutions", "kind", messageMultipleAnswers);
        System.out.println("Now please choose the <3> Status of Institution");
        validateInput(sc, 3);
        List<WrapperHttpResp> jsonMappedHttpStatusOfInstitutions = objectMapper.readValue(
            universityStatuses,
            new TypeReference<>() {}
        );
        showChosenOptionDetails(jsonMappedHttpStatusOfInstitutions,
            sc, httpBody, "Status of Institution", "statusCodes", messageMultipleAnswers);
        System.out.println("Now please choose the <4> Supervising authority");
        validateInput(sc, 4);
        List<WrapperHttpResp> jsonMappedHttpSupervisingAuthorities = objectMapper.readValue(
            responseSupervisingAuthorities,
            new TypeReference<>() {}
        );
        showChosenOptionDetails(jsonMappedHttpSupervisingAuthorities, sc, httpBody, "Supervising authority",
            "supervisingInstitutionIds", messageMultipleAnswers);
        if (instCodes.contains("1") || instCodes.contains("10") || instCodes.contains("13")) {
            System.out.println("Now please choose the <5> Type of university");
            validateInput(sc, 5);
            List<WrapperHttpResp> jsonMappedHttpTypeOfUniversity = objectMapper.readValue(
                responseUniTypes,
                new TypeReference<>() {}
            );
            showChosenOptionDetails(jsonMappedHttpTypeOfUniversity, sc, httpBody, "Type of university", "uTypeCd", messageOneOption);
            List<String> options  = (List<String>) httpBody.getFilter().get("uTypeCd");
            if (options!= null && !options.isEmpty()) {
                httpBody.getFilter().put("uTypeCd", options.get(0));
            }
        } else {
            System.out.println("Skipping choosing <5> Type of University, to have this option\n "
                + "<Ecclesiastical University> or <Nonpublic University> or <Public University> options needed to be chosen before");
        }

        if (instCodes.contains("5")) {
            System.out.println("Now please choose the <6> Type of scientific institution");
            validateInput(sc, 6);
            List<WrapperHttpResp> jsonMappedHttpsScientificInstitutionType = objectMapper.readValue(
                scientificInstitutionTypes,
                new TypeReference<>() {}
            );
            showChosenOptionDetails(jsonMappedHttpsScientificInstitutionType, sc, httpBody, "Type of scientific institution", "siTypeCd", messageMultipleAnswers);
        } else {
            System.out.println("Skipping choosing <6> Type of scientific institution, to have this option\n "
                + "<Scientific Institution> options needed to be chosen before");
        }

        final String responseBody = sentHttpRequest(objectMapper.writeValueAsString(httpBody), GENERAL_UNI_INFO_API);
        final ResponseResults initialInstitutionResponse = objectMapper.readValue(responseBody, ResponseResults.class);
        final int totalCount  = initialInstitutionResponse.getTotalCount();
        final HttpBody fullHttpReq = HttpBody.builder()
                .offset(INITIAL_PAGING_OFFSET)
                .size(totalCount - 1)
                .objectTypes(httpBody.getObjectTypes())
                .sorting(httpBody.getSorting())
                .filter(httpBody.getFilter())
                .build();

        final ResponseResults finaInstitutionResponse = objectMapper.readValue(sentHttpRequest(objectMapper.writeValueAsString(fullHttpReq), GENERAL_UNI_INFO_API), ResponseResults.class);
        System.out.println("Writing the results in institutions.csv");

        // Future Change Incorporate Count
        final Map<String, String> uniNameAndId = finaInstitutionResponse.getResults()
            .stream()
            .collect(Collectors.toMap(InstitutionResponse::getName, InstitutionResponse::getId));

        final InstitutionInfoCollection allPossibleUniNameAndCodes = objectMapper.readValue(
            new File(Paths.get("").toAbsolutePath().toString().concat("/src/main/java/org/example/inst_enum_code.json")),
            new TypeReference<>() {}
        );

        final LinkedHashMap<String, Integer> allUniNameValueMap = allPossibleUniNameAndCodes.getEnumValues().parallelStream()
                .map(institutionInfo ->Map.entry(institutionInfo.getName(), institutionInfo.getValue()))
                 .collect(LinkedHashMap::new,
                        ((linkedHashMap, stringIntegerEntry) -> linkedHashMap.put(stringIntegerEntry.getKey(),stringIntegerEntry.getValue())),
                        (HashMap::putAll));

        final Map<String, Integer> relatableUniValueMap = allUniNameValueMap.entrySet()
            .stream()
            .filter(stringIntegerEntry -> uniNameAndId.get(stringIntegerEntry.getKey()) != null)
            .collect(Collectors.toMap(Map.Entry::getKey, Map.Entry::getValue));

        final Map<String, Map<String, Integer>> uniByYearAndCount = new LinkedHashMap<>();

        for(Map.Entry<String, Integer> en : relatableUniValueMap.entrySet()) {
            ParamObject paramObject = new ParamObject();
            paramObject.setEnumValues(allPossibleUniNameAndCodes.getEnumValues());
            paramObject.setValue(List.of(en.getValue()));
            HTTPInstitutionCountBody httpInstitutionCountBody = HTTPInstitutionCountBody.builder()
                .params(List.of(paramObject)).build();
            String response = sentHttpRequest(objectMapper.writeValueAsString(httpInstitutionCountBody), INSTITUTION_SPECIFIC_API);
            JsonNode jsonNodeRoot = objectMapper.readTree(response);
            JsonNode sectionsNode = jsonNodeRoot.get("sections");
            StreamSupport.stream(sectionsNode.spliterator(), false)
                .filter(jsonNode -> "CHART".equals(jsonNode.get("type").asText()) && "chart_1".equals(jsonNode.get("id")
                    .asText()))
                .findFirst()
                .map(jsonNode -> jsonNode.get("datasets"))
                .ifPresent(
                    arrJsonNode -> StreamSupport.stream(arrJsonNode.spliterator(), false)
                    .filter(jsonNode -> "number of students".equals(jsonNode.get("label").asText()))
                    .findFirst()
                    .map(jsonNode -> jsonNode.get("data"))
                    .ifPresent(jsonNode -> StreamSupport.stream(jsonNode.spliterator(), false)
                            .forEach(jsonNode1 -> {
                                uniByYearAndCount.putIfAbsent(
                                    en.getKey(),
                                    new LinkedHashMap<>(Map.of(jsonNode1.get("x").asText(), jsonNode1.get("y").asInt()))
                                );
                                uniByYearAndCount.get(en.getKey()).put(jsonNode1.get("x").asText(), jsonNode1.get("y").asInt());
                            }
                       )
                    )
                );
        }
        writeUniYearCount(uniByYearAndCount, uniNameAndId, "institution_counts.csv");
        writeResponseResultsToCsv(finaInstitutionResponse, "institutions.csv");
    }
}