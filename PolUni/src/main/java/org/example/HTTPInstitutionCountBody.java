package org.example;

import java.util.List;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@NoArgsConstructor
@AllArgsConstructor
@Getter
@Setter
@Builder
public class HTTPInstitutionCountBody
{
    @Builder.Default
    private String id = "studenci_2024";

    @Builder.Default
    private String lang = "en";

    private List<ParamObject> params;



}
